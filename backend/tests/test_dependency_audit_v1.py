import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('dart_audit', Path(__file__).parents[2] / 'scripts/dart_dependency_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
LOCK = {'packages': {'http': {'source': 'hosted', 'version': '1.2.3'},
                     'flutter': {'source': 'sdk', 'version': '0.0.0'}}}


def test_exact_versions_and_sdk_coverage_are_explicit():
    def response(queries):
        assert queries == [{'package': {'name': 'http', 'ecosystem': 'Pub'}, 'version': '1.2.3'}]
        return {'results': [{}]}
    result = audit.audit(LOCK, response)
    assert result['status'] == 'no_known_advisories'
    assert result['packages_checked'] == 1 and len(result['skipped']) == 1


@pytest.mark.parametrize('response', [{'results': []}, {'results': [{'next_page_token': 'more'}]},
                                      {'results': [{'vulns': ['malformed']}]}, {'error': 'unavailable'}])
def test_incomplete_advisory_queries_never_report_clean(response):
    with pytest.raises(ValueError):
        audit.audit(LOCK, lambda _: response)


def test_report_preserves_advisory_id():
    result = audit.audit(LOCK, lambda _: {'results': [{'vulns': [{'id': 'TEST-ADVISORY'}]}]})
    assert result['status'] == 'findings'
    assert result['dependencies'][0]['advisories'] == ['TEST-ADVISORY']
