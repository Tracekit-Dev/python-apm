"""Tests for URL resolution logic in TraceKit Python SDK."""

import pytest
from tracekit.client import _resolve_endpoint, _extract_base_url


class TestResolveEndpoint:
    """Test cases for _resolve_endpoint function."""

    # Just host cases
    def test_just_host_with_ssl(self):
        result = _resolve_endpoint('app.tracekit.dev', '/v1/traces', True)
        assert result == 'https://app.tracekit.dev/v1/traces'

    def test_just_host_without_ssl(self):
        result = _resolve_endpoint('localhost:8081', '/v1/traces', False)
        assert result == 'http://localhost:8081/v1/traces'

    def test_just_host_with_trailing_slash(self):
        result = _resolve_endpoint('app.tracekit.dev/', '/v1/metrics', True)
        assert result == 'https://app.tracekit.dev/v1/metrics'

    # Host with scheme cases
    def test_http_with_host_only(self):
        result = _resolve_endpoint('http://localhost:8081', '/v1/traces', True)
        assert result == 'http://localhost:8081/v1/traces'

    def test_https_with_host_only(self):
        result = _resolve_endpoint('https://app.tracekit.dev', '/v1/metrics', False)
        assert result == 'https://app.tracekit.dev/v1/metrics'

    def test_http_with_host_and_trailing_slash(self):
        result = _resolve_endpoint('http://localhost:8081/', '/v1/traces', True)
        assert result == 'http://localhost:8081/v1/traces'

    # Full URL cases
    def test_full_url_with_standard_path(self):
        result = _resolve_endpoint('http://localhost:8081/v1/traces', '/v1/traces', True)
        assert result == 'http://localhost:8081/v1/traces'

    def test_full_url_with_custom_path(self):
        result = _resolve_endpoint('http://localhost:8081/custom/path', '/v1/traces', True)
        assert result == 'http://localhost:8081/custom/path'

    def test_full_url_with_trailing_slash(self):
        result = _resolve_endpoint('https://app.tracekit.dev/api/v2/', '/v1/traces', False)
        assert result == 'https://app.tracekit.dev/api/v2'

    # Edge cases
    def test_empty_path_for_snapshots(self):
        result = _resolve_endpoint('app.tracekit.dev', '', True)
        assert result == 'https://app.tracekit.dev'

    def test_http_with_empty_path(self):
        result = _resolve_endpoint('http://localhost:8081', '', True)
        assert result == 'http://localhost:8081'

    def test_http_with_trailing_slash_and_empty_path(self):
        result = _resolve_endpoint('http://localhost:8081/', '', True)
        assert result == 'http://localhost:8081'

    def test_snapshot_with_full_url_extracts_base_http(self):
        result = _resolve_endpoint('http://localhost:8081/v1/traces', '', True)
        assert result == 'http://localhost:8081'

    def test_snapshot_with_full_url_extracts_base_https(self):
        result = _resolve_endpoint('https://app.tracekit.dev/v1/traces', '', False)
        assert result == 'https://app.tracekit.dev'


class TestExtractBaseURL:
    """Test cases for _extract_base_url function."""

    def test_extract_base_from_traces_endpoint_http(self):
        result = _extract_base_url('http://localhost:8081/v1/traces')
        assert result == 'http://localhost:8081'

    def test_extract_base_from_traces_endpoint_https(self):
        result = _extract_base_url('https://app.tracekit.dev/v1/traces')
        assert result == 'https://app.tracekit.dev'

    def test_extract_base_from_metrics_endpoint(self):
        result = _extract_base_url('https://app.tracekit.dev/v1/metrics')
        assert result == 'https://app.tracekit.dev'

    def test_keep_custom_path_urls_as_is(self):
        result = _extract_base_url('http://localhost:8081/custom')
        assert result == 'http://localhost:8081/custom'

    def test_keep_custom_base_path_urls_as_is(self):
        result = _extract_base_url('http://localhost:8081/api')
        assert result == 'http://localhost:8081/api'

    def test_extract_from_api_v1_traces_path(self):
        result = _extract_base_url('https://app.tracekit.dev/api/v1/traces')
        assert result == 'https://app.tracekit.dev'

    def test_extract_from_api_v1_metrics_path(self):
        result = _extract_base_url('https://app.tracekit.dev/api/v1/metrics')
        assert result == 'https://app.tracekit.dev'

    def test_return_as_is_when_no_path_component(self):
        result = _extract_base_url('https://app.tracekit.dev')
        assert result == 'https://app.tracekit.dev'

    def test_return_as_is_when_no_scheme(self):
        result = _extract_base_url('app.tracekit.dev/v1/traces')
        assert result == 'app.tracekit.dev/v1/traces'


class TestEndpointResolutionIntegration:
    """Integration tests for full endpoint resolution scenarios."""

    @pytest.mark.parametrize('endpoint,traces_path,metrics_path,use_ssl,expected', [
        # Default production config
        (
            'app.tracekit.dev',
            '/v1/traces',
            '/v1/metrics',
            True,
            {
                'traces': 'https://app.tracekit.dev/v1/traces',
                'metrics': 'https://app.tracekit.dev/v1/metrics',
                'snapshots': 'https://app.tracekit.dev',
            }
        ),
        # Local development
        (
            'localhost:8080',
            '/v1/traces',
            '/v1/metrics',
            False,
            {
                'traces': 'http://localhost:8080/v1/traces',
                'metrics': 'http://localhost:8080/v1/metrics',
                'snapshots': 'http://localhost:8080',
            }
        ),
        # Custom paths
        (
            'app.tracekit.dev',
            '/api/v2/traces',
            '/api/v2/metrics',
            True,
            {
                'traces': 'https://app.tracekit.dev/api/v2/traces',
                'metrics': 'https://app.tracekit.dev/api/v2/metrics',
                'snapshots': 'https://app.tracekit.dev',
            }
        ),
        # Full URLs provided
        (
            'http://localhost:8081/custom',
            '/v1/traces',
            '/v1/metrics',
            True,  # Should be ignored
            {
                'traces': 'http://localhost:8081/custom',
                'metrics': 'http://localhost:8081/custom',
                'snapshots': 'http://localhost:8081/custom',
            }
        ),
        # Trailing slash handling
        (
            'http://localhost:8081/',
            '/v1/traces',
            '/v1/metrics',
            False,
            {
                'traces': 'http://localhost:8081/v1/traces',
                'metrics': 'http://localhost:8081/v1/metrics',
                'snapshots': 'http://localhost:8081',
            }
        ),
        # Full URL with path - snapshots extract base
        (
            'http://localhost:8081/v1/traces',
            '/v1/traces',
            '/v1/metrics',
            True,  # Should be ignored
            {
                'traces': 'http://localhost:8081/v1/traces',
                'metrics': 'http://localhost:8081/v1/traces',
                'snapshots': 'http://localhost:8081',  # Should extract base URL
            }
        ),
    ])
    def test_endpoint_resolution_scenarios(self, endpoint, traces_path, metrics_path, use_ssl, expected):
        """Test various endpoint resolution scenarios."""
        # Resolve endpoints
        traces_endpoint = _resolve_endpoint(endpoint, traces_path, use_ssl)
        metrics_endpoint = _resolve_endpoint(endpoint, metrics_path, use_ssl)
        snapshot_endpoint = _resolve_endpoint(endpoint, '', use_ssl)

        assert traces_endpoint == expected['traces']
        assert metrics_endpoint == expected['metrics']
        assert snapshot_endpoint == expected['snapshots']
