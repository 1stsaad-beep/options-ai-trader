package com.optionsaitrader.options_ai_trader;

import java.net.URI;
import java.util.Map;

/** Pure Java policy: bounded, read-only monitoring of our server, never a broker. */
public final class MonitorPolicy {
    public static final long SESSION_MS = 30 * 60 * 1000L;
    public static final long POLL_MS = 60 * 1000L;
    public static final int MAX_BODY_BYTES = 512 * 1024;
    private MonitorPolicy() {}

    public static URI endpoint(String base, String account, String token) {
        if (base == null || account == null || token == null ||
                !account.matches("[A-Za-z0-9_-]{1,128}") || !token.matches("[!-~]{8,4096}")) {
            throw new IllegalArgumentException("INVALID_MONITOR_CONFIG");
        }
        URI uri = URI.create(base);
        String host = uri.getHost();
        String path = uri.getRawPath();
        if (!"https".equals(uri.getScheme()) || host == null || host.isEmpty() ||
                uri.getUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null ||
                (uri.getPort() != -1 && (uri.getPort() < 1 || uri.getPort() > 65535)) ||
                path == null || !path.matches("[A-Za-z0-9_/-]*") || path.contains("//")) {
            throw new IllegalArgumentException("HTTPS_SERVER_REQUIRED");
        }
        host = host.toLowerCase(java.util.Locale.ROOT).replaceAll("\\.+$", "");
        if (host.equals("alpaca.markets") || host.endsWith(".alpaca.markets") ||
                host.equals("interactivebrokers.com") || host.endsWith(".interactivebrokers.com") ||
                host.equals("ibkr.com") || host.endsWith(".ibkr.com")) {
            throw new IllegalArgumentException("BROKER_HOST_FORBIDDEN");
        }
        return URI.create(base.replaceAll("/+$", "") + "/api/accounts/" + account + "/market-runtime/status");
    }

    public static boolean expired(long started, long now) {
        return now < started || now - started >= SESSION_MS;
    }

    public static boolean validStatus(Map<String, Object> value, String account) {
        if (!Integer.valueOf(1).equals(value.get("schema_version")) ||
                !account.equals(value.get("account_id")) ||
                !"real_market_virtual".equals(value.get("mode")) ||
                !(value.get("heartbeat_fresh") instanceof Boolean) ||
                !(value.get("state") instanceof String)) return false;
        for (String key : new String[] {"external_orders_enabled", "virtual_fills_enabled",
                "new_risk_allowed", "stop_loss_execution_assumed"}) {
            if (!Boolean.FALSE.equals(value.get(key))) return false;
        }
        return true;
    }
}
