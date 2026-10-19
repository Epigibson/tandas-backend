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
from app.models.round import TandaRound
from app.models.tanda import Tanda
from app.schemas.payment import PaymentResponse, PaymentSubmitProof, PaymentReview
from app.services.payment_service import process_payment_review

router = APIRouter()


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

    payment = Payment(
        tanda_id=tanda.id,
        round_id=tanda_round.id,
        payer_user_id=current_user.id,
        slot_number=tanda_round.slot_number_beneficiary,
        amount=tanda.contribution_amount,
        late_fee=0.0,
        status=PaymentStatus.SUBMITTED,
        proof_image_url=payload.proof_image_url
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


@router.get("/tanda/{tanda_id}", response_model=List[PaymentResponse])
async def list_payments_for_tanda(
    tanda_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Payment)
        .where(Payment.tanda_id == tanda_id)
        .order_by(Payment.created_at.desc())
        .options(selectinload(Payment.payer))
    )
    res = await db.execute(stmt)
    return res.scalars().all()


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
        reviewer_user_id=current_user.id,
        approved=review_in.approved,
        rejection_reason=review_in.rejection_reason
    )
    return payment
