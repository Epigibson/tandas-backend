from typing import List
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.payment import Payment, PaymentStatus
from app.models.round import TandaRound, RoundStatus
from app.models.tanda import Tanda, TandaStatus
from app.schemas.payment import PaymentResponse, PaymentSubmitProof, PaymentReview
from app.services.payment_service import process_payment_review
from app.services.tanda_access import count_user_slots, ensure_member, can_manage
from app.models.audit import ActivityAuditLog
from app.services import storage_service
from app.services.realtime_service import notify_tanda_changed

router = APIRouter()


async def _with_signed_proofs(payments: List[Payment]) -> List[PaymentResponse]:
    """Cambia las referencias storage:// por URLs firmadas que caducan."""
    signed = await storage_service.sign_receipt_refs(p.proof_image_url for p in payments)
    responses = []
    for p in payments:
        response = PaymentResponse.model_validate(p)
        if response.proof_image_url and response.proof_image_url.startswith(storage_service.STORAGE_REF_PREFIX):
            response.proof_image_url = signed.get(response.proof_image_url)
        responses.append(response)
    return responses


async def _load_payment_with_payer(db: AsyncSession, payment_id: UUID) -> Payment:
    # La respuesta incluye `payer`; en async no se puede cargar de forma perezosa al serializar
    stmt = (
        select(Payment)
        .where(Payment.id == payment_id)
        .options(selectinload(Payment.payer))
        .execution_options(populate_existing=True)
    )
    res = await db.execute(stmt)
    return res.scalar_one()


@router.post("/round/{round_id}/submit", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def submit_payment(
    round_id: UUID,
    payload: PaymentSubmitProof,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Un participante sube su comprobante de pago para una ronda específica.
    """
    round_stmt = select(TandaRound).where(TandaRound.id == round_id)
    round_res = await db.execute(round_stmt)
    tanda_round = round_res.scalar_one_or_none()

    if not tanda_round:
        raise HTTPException(status_code=404, detail="Ronda no encontrada")

    tanda_stmt = select(Tanda).where(Tanda.id == tanda_round.tanda_id)
    tanda_res = await db.execute(tanda_stmt)
    tanda = tanda_res.scalar_one_or_none()

    if not tanda:
        raise HTTPException(status_code=404, detail="Tanda no encontrada")

    payer_id = payload.payer_user_id or current_user.id
    on_behalf = payer_id != current_user.id
    if on_behalf and not can_manage(tanda, current_user):
        raise HTTPException(status_code=403, detail="Solo el organizador puede registrar aportaciones de otros")
    my_slots = await count_user_slots(db, tanda.id, payer_id)
    if my_slots == 0:
        raise HTTPException(status_code=403, detail="Solo los participantes con número pueden aportar")
    if tanda.status != TandaStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="La tanda todavía no inicia")
    if tanda_round.status != RoundStatus.COLLECTING:
        raise HTTPException(status_code=400, detail="Esta ronda no está recibiendo aportaciones")
    # Solo se aceptan comprobantes subidos por /upload/receipt
    if not payload.proof_image_url.startswith(storage_service.valid_receipt_prefix()):
        raise HTTPException(status_code=400, detail="Comprobante no válido")

    existing_stmt = select(Payment.id).where(
        Payment.round_id == tanda_round.id,
        Payment.payer_user_id == payer_id,
        Payment.status.in_([PaymentStatus.SUBMITTED, PaymentStatus.APPROVED])
    ).limit(1)
    if (await db.execute(existing_stmt)).scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Esa persona ya tiene su aportación de esta ronda" if on_behalf else "Ya enviaste tu aportación de esta ronda"
        )

    payment = Payment(
        tanda_id=tanda.id,
        round_id=tanda_round.id,
        payer_user_id=payer_id,
        slot_number=tanda_round.slot_number_beneficiary,
        # Un solo comprobante cubre todos los números que tenga el participante
        amount=tanda.contribution_amount * my_slots,
        late_fee=0.0,
        status=PaymentStatus.SUBMITTED,
        proof_image_url=payload.proof_image_url
    )
    db.add(payment)
    if on_behalf:
        db.add(ActivityAuditLog(
            tanda_id=tanda.id,
            user_id=current_user.id,
            action="PAYMENT_SUBMITTED_ON_BEHALF",
            description=f"{current_user.full_name} registró una aportación a nombre de otro participante."
        ))
    await db.commit()
    notify_tanda_changed(tanda.id)
    created = await _load_payment_with_payer(db, payment.id)
    return (await _with_signed_proofs([created]))[0]


@router.get("/tanda/{tanda_id}", response_model=List[PaymentResponse])
async def list_payments_for_tanda(
    tanda_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    tanda = (await db.execute(select(Tanda).where(Tanda.id == tanda_id))).scalar_one_or_none()
    if not tanda:
        raise HTTPException(status_code=404, detail="Tanda no encontrada")
    await ensure_member(db, tanda, current_user)

    stmt = (
        select(Payment)
        .where(Payment.tanda_id == tanda_id)
        .order_by(Payment.created_at.desc())
        .options(selectinload(Payment.payer))
    )
    res = await db.execute(stmt)
    return await _with_signed_proofs(list(res.scalars().all()))


@router.post("/{payment_id}/review", response_model=PaymentResponse)
async def review_payment(
    payment_id: UUID,
    review_in: PaymentReview,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    El organizador aprueba o rechaza el comprobante de pago de un participante.
    """
    payment = await process_payment_review(
        db=db,
        payment_id=payment_id,
        reviewer=current_user,
        approved=review_in.approved,
        rejection_reason=review_in.rejection_reason
    )
    notify_tanda_changed(payment.tanda_id)
    reviewed = await _load_payment_with_payer(db, payment.id)
    return (await _with_signed_proofs([reviewed]))[0]
