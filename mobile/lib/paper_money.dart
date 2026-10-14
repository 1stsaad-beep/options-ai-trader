/// Exact integer ledger arithmetic, including products before division. JSON
/// portability is deliberately limited to +/- (2^53-1), even on a 64-bit VM.
const paperMaxMoney=9007199254740991;
int _amount(BigInt value) {
  if(value.abs()>BigInt.from(paperMaxMoney))throw const FormatException('Paper amount exceeds exact ledger range');
  return value.toInt();
}
int paperProduct(int a,int b)=>_amount(BigInt.from(a)*BigInt.from(b));
int paperSum(int a,int b)=>_amount(BigInt.from(a)+BigInt.from(b));
int paperPortion(int cost,int quantity,int total) {
  if(cost<0||cost>paperMaxMoney||quantity<0||total<=0||quantity>total)throw const FormatException('Invalid paper allocation');
  return _amount(BigInt.from(cost)*BigInt.from(quantity)~/BigInt.from(total));
}
