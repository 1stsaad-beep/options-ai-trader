import com.optionsaitrader.options_ai_trader.MonitorPolicy;
import java.util.HashMap;
import java.util.Map;

/** Runs with the JDK only, against the exact policy used by Android. */
public class MonitorPolicyTest {
    static int checks = 0;
    static void require(boolean value) { checks++; if (!value) throw new AssertionError("check " + checks); }
    static void refused(String base, String account, String token) {
        try { MonitorPolicy.endpoint(base, account, token); throw new AssertionError("unsafe endpoint accepted"); }
        catch (IllegalArgumentException expected) { checks++; }
    }
    public static void main(String[] args) {
        String token = "offline-fixture-token";
        require(MonitorPolicy.endpoint("https://runtime.invalid/prefix/", "account-one", token).toString()
            .equals("https://runtime.invalid/prefix/api/accounts/account-one/market-runtime/status"));
        for (String base : new String[] {"http://runtime.invalid", "https://user@runtime.invalid", "https://runtime.invalid/?token=x",
                "https://runtime.invalid/#fragment", "https://runtime.invalid/../orders", "https://runtime.invalid/%2e%2e",
                "https://data.alpaca.markets", "https://paper-api.alpaca.markets", "https://api.ibkr.com",
                "https://api.interactivebrokers.com", "https://data.alpaca.markets.", "https://runtime.invalid:99999"}) {
            refused(base, "account-one", token);
        }
        refused("https://runtime.invalid", "a/../../orders", token);
        refused("https://runtime.invalid", "a", "injected\r\nheader");
        refused("https://runtime.invalid", "a", "");
        require(!MonitorPolicy.expired(100, 101));
        require(MonitorPolicy.expired(100, 100 + MonitorPolicy.SESSION_MS));
        require(MonitorPolicy.expired(100, 99));
        Map<String,Object> status = new HashMap<>();
        status.put("schema_version", 1); status.put("account_id", "account-one");
        status.put("mode", "real_market_virtual"); status.put("state", "DISABLED");
        status.put("heartbeat_fresh", false);
        for (String key : new String[]{"external_orders_enabled", "virtual_fills_enabled", "new_risk_allowed", "stop_loss_execution_assumed"}) status.put(key, false);
        require(MonitorPolicy.validStatus(status, "account-one"));
        require(!MonitorPolicy.validStatus(status, "account-two"));
        for (String key : new String[]{"external_orders_enabled", "virtual_fills_enabled", "new_risk_allowed", "stop_loss_execution_assumed"}) {
            status.put(key, true); require(!MonitorPolicy.validStatus(status, "account-one"));
            status.remove(key); require(!MonitorPolicy.validStatus(status, "account-one"));
            status.put(key, false);
        }
        status.put("schema_version", "1"); require(!MonitorPolicy.validStatus(status, "account-one"));
        System.out.println("Native monitor policy: " + checks + " checks passed; no Android device or network used");
    }
}
