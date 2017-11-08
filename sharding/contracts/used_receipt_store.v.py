used_receipts: public(bool[num])

@payable
def add_used_receipt(receipt_id: num) -> bool:
    assert msg.sender == self
    assert not self.used_receipts[receipt_id]
    self.used_receipts[receipt_id] = True
    raw_log([sha3("add_used_receipt()")], concat('', as_bytes32(receipt_id)))
    return True
