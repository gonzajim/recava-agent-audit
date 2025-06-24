from google.cloud import firestore
from src.config import db, logger

@firestore.transactional
def _deduct_one_credit(transaction, user_ref):
    snapshot = user_ref.get(transaction=transaction)
    credits = snapshot.get('credits', 0)
    if credits <= 0:
        raise ValueError('INSUFFICIENT_CREDITS')
    transaction.update(user_ref, {'credits': credits - 1})
    return credits - 1

def deduct_user_credit(uid: str) -> bool:
    """Attempt to deduct one credit for the given user. Returns True if success."""
    user_ref = db.collection('users').document(uid)
    transaction = db.transaction()
    try:
        _deduct_one_credit(transaction, user_ref)
        logger.info(f'Deducted one credit for user {uid}')
        return True
    except ValueError:
        logger.info(f'User {uid} has no credits')
        return False


