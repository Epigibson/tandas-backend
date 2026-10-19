from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.payment import Payment, PaymentStatus
from app.models.round import TandaRound, RoundStatus
from app.models.tanda import Tanda
from app.models.user import User
from app.models.audit import ActivityAuditLog


async def process_payment_review(
    db: AsyncSession,
    payment_id: UUID,
    reviewer_user_id: UUID,
    approved: bool,
    rejection_reason: str = None
) -> Payment:
    stmt = select(Payment).where(Payment.id == payment_id)
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pago no encontrado"
        )
    
    # Validar que el revisor sea organizador de la tanda
    tanda_stmt = select(Tanda).where(Tanda.id == payment.tanda_id)
    tanda_res = await db.execute(tanda_stmt)
    tanda = tanda_res.scalar_one_or_none()
    
    if not tanda or tanda.organizer_id != reviewer_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el organizador de la tanda puede revisar comprobantes"
        )

    if approved:
        payment.status = PaymentStatus.APPROVED
        payment.verified_by_user_id = reviewer_user_id
        payment.verified_at = datetime.now(timezone.utc)
        payment.rejection_reason = None

        # Actualizar acumulado de la ronda
        round_stmt = select(TandaRound).where(TandaRound.id == payment.round_id)
        round_res = await db.execute(round_stmt)
        tanda_round = round_res.scalar_one_or_none()
        
        if tanda_round:
            tanda_round.collected_amount += payment.amount
            if tanda_round.collected_amount >= tanda_round.expected_amount:
                tanda_round.status = RoundStatus.COMPLETED_PENDING_PAYOUT

        # Mejorar score del usuario por pago puntual
        user_stmt = select(User).where(User.id == payment.payer_user_id)
        user_res = await db.execute(user_stmt)
        payer = user_res.scalar_one_or_none()
        if payer:
            payer.on_time_payments += 1
            if payer.tanda_score < 100:
                payer.tanda_score = min(100, payer.tanda_score + 2)

        # Audit log
        audit = ActivityAuditLog(
            tanda_id=payment.tanda_id,
            user_id=reviewer_user_id,
            action="PAYMENT_APPROVED",
            description=f"Aportación de ${payment.amount} MXN (Turno #{payment.slot_number}) aprobada."
        )
        db.add(audit)

    else:
        payment.status = PaymentStatus.REJECTED
        payment.rejection_reason = rejection_reason or "Comprobante rechazado por el organizador"
        payment.verified_by_user_id = reviewer_user_id
        payment.verified_at = datetime.now(timezone.utc)

        # Audit log
        audit = ActivityAuditLog(
            tanda_id=payment.tanda_id,
            user_id=reviewer_user_id,
            action="PAYMENT_REJECTED",
            description=f"Aportación rechazada: {payment.rejection_reason}"
        )
        db.add(audit)

    await db.commit()
    await db.refresh(payment)
    return payment
