Map<String, dynamic> researchEnvelope({String account = 'a', String symbol = 'NVDA'}) => {
  'schema_version': 1, 'account_id': account, 'symbol': symbol,
  'mode': 'SHADOW', 'source': 'synthetic_fixture',
  'execution_authority': false, 'external_connections': false,
  'profitability_evidence': false,
};

Map<String, dynamic> researchFixture({String account = 'a', String symbol = 'NVDA'}) => {
  ...researchEnvelope(account: account, symbol: symbol),
  'as_of': '2026-01-05T15:00:30Z', 'observed_at': '2026-01-05T15:00:00Z',
  'contract': {'contract_id': 'contract-$symbol', 'symbol': symbol, 'right': 'CALL'},
  'decision': {
    'account_id': account, 'decision_id': 'decision-$account',
    'contract_id': 'contract-$symbol', 'decided_at': '2026-01-05T15:00:30Z',
    'observed_at': '2026-01-05T15:00:00Z', 'reasons': ['ORIGINAL_SAVED_REASON'],
    'digest': 'decision-digest-$account', 'evidence_json': '{"source":"synthetic_fixture"}',
  },
  'modules': {'option_twin': {'observed': account}},
  'limitations': ['synthetic-$account'],
};

Map<String, dynamic> researchListFixture({String account = 'a', String symbol = 'NVDA',
    bool saved = false}) => {
  ...researchEnvelope(account: account, symbol: symbol), 'truncated': false,
  'items': [if (saved) {
    'snapshot_id': 'saved-$account', 'account_id': account, 'symbol': symbol,
    'as_of': '2026-01-05T15:00:30Z', 'decided_at': '2026-01-05T15:00:30Z',
    'decision_id': 'decision-$account', 'digest': 'snapshot-digest-$account',
  }],
};

Map<String, dynamic> researchSavedFixture({String account = 'a', String symbol = 'NVDA'}) => {
  ...researchEnvelope(account: account, symbol: symbol),
  'snapshot_id': 'saved-$account', 'workbench': researchFixture(account: account, symbol: symbol),
};

Map<String, dynamic> researchObservationFixture({String account = 'a', String symbol = 'NVDA'}) => {
  ...researchEnvelope(account: account, symbol: symbol), 'snapshot_id': 'saved-$account',
  'observed_at': '2026-01-05T15:01:00Z', 'captured_at': '2026-01-05T15:01:30Z',
  'quote_model_version': 'synthetic-option-fixture-v1',
  'contract_id': 'contract-$symbol', 'bid': 3.1, 'ask': 3.15,
};

Map<String, dynamic> researchReplayFixture({String account = 'a', String symbol = 'NVDA',
    bool outcome = false}) => {
  ...researchEnvelope(account: account, symbol: symbol), 'snapshot_id': 'saved-$account',
  'as_of': '2026-01-05T15:00:30Z', 'outcome_as_of': '2026-01-05T15:02:00Z',
  'original_workbench': researchFixture(account: account, symbol: symbol),
  'original_decision': researchFixture(account: account, symbol: symbol)['decision'],
  'counterfactual': {
    'mode': 'SHADOW', 'counterfactual': true, 'execution_authority': false,
    'profitability_evidence': false, 'decision_digest': 'decision-digest-$account',
    'decision_reasons': ['ORIGINAL_SAVED_REASON'],
    'status': outcome ? 'REPLAYED' : 'INSUFFICIENT_OBSERVED_OUTCOME',
    'pnl': outcome ? 1.25 : null,
    if (outcome) ...{
      'entry_at': '2026-01-05T15:01:00Z', 'exit_at': '2026-01-05T15:02:00Z',
      'commissions': 1.3,
    },
  },
};
