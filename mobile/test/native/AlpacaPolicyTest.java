import com.optionsaitrader.options_ai_trader.AlpacaPolicy;
import java.time.Instant;
import java.util.List;
public class AlpacaPolicyTest {
    private static int count;
    private static void check(boolean v){count++;if(!v)throw new AssertionError("check "+count);}
    public static void main(String[] args){
        for(String host:List.of("api.alpaca.markets","paper-api.alpaca.markets","evil.example","data.alpaca.markets.evil.example"))
            check(!AlpacaPolicy.permits("GET","https://"+host+"/v2/stocks/bars"));
        for(String method:List.of("POST","PUT","PATCH","DELETE"))check(!AlpacaPolicy.permits(method,"https://data.alpaca.markets/v2/stocks/bars"));
        for(String path:List.of("/v2/orders","/v2/account","/v2/stocks/../orders","/v2/stocks/%2e%2e/orders"))
            check(!AlpacaPolicy.permits("GET","https://data.alpaca.markets"+path));
        for(String url:List.of("http://data.alpaca.markets/v2/stocks/bars","https://user@data.alpaca.markets/v2/stocks/bars","https://data.alpaca.markets:443/v2/stocks/bars","https://data.alpaca.markets/v2/stocks/bars#x"))check(!AlpacaPolicy.permits("GET",url));
        check(AlpacaPolicy.permits("GET","https://data.alpaca.markets/v2/stocks/quotes/latest?symbols=NVDA&feed=iex"));
        check(!AlpacaPolicy.permits("POST","https://data.alpaca.markets/v2/stocks/quotes/latest"));
        check(AlpacaPolicy.permits("GET","https://data.alpaca.markets/v2/stocks/bars?feed=iex"));
        check(AlpacaPolicy.permits("GET","https://data.alpaca.markets/v1beta1/options/snapshots?feed=opra"));
        check(AlpacaPolicy.permits("GET","https://stream.data.alpaca.markets/v2/iex"));
        check(!AlpacaPolicy.permits("GET","https://stream.data.alpaca.markets/v2/iex?token=x"));
        check(AlpacaPolicy.symbol("BRK.B"));check(!AlpacaPolicy.symbol("NVDA/../../orders"));
        check(AlpacaPolicy.contract("AAPL261016C00250000"));check(!AlpacaPolicy.contract("AAPL"));
        check(AlpacaPolicy.inSession(Instant.parse("2026-07-13T13:30:00Z").toEpochMilli(),"regular"));
        check(!AlpacaPolicy.inSession(Instant.parse("2026-01-13T13:30:00Z").toEpochMilli(),"regular"));
        check(AlpacaPolicy.inSession(Instant.parse("2026-01-13T14:30:00Z").toEpochMilli(),"regular"));
        check(!AlpacaPolicy.inSession(Instant.parse("2026-01-13T21:00:00Z").toEpochMilli(),"regular"));
        check(AlpacaPolicy.inSession(Instant.parse("2026-01-13T21:00:00Z").toEpochMilli(),"extended"));
        check(!AlpacaPolicy.inSession(Instant.parse("2026-01-17T15:00:00Z").toEpochMilli(),"extended"));
        check(!AlpacaPolicy.freshBar(100000,120000));check(AlpacaPolicy.freshBar(100000,200000));check(!AlpacaPolicy.freshBar(100000,300000));
        check(AlpacaPolicy.validBar(10,12,9,11,100));check(!AlpacaPolicy.validBar(10,9,8,11,100));check(!AlpacaPolicy.validBar(10,12,9,11,Double.NaN));
        check(AlpacaPolicy.terminal(406));check(AlpacaPolicy.terminal(403));check(!AlpacaPolicy.terminal(429));
        check(AlpacaPolicy.retryMs(10)==120000);check(AlpacaPolicy.retryMs(0)==5000);
        check(AlpacaPolicy.rsi(List.of(1.0,2.0))==null);
        System.out.println("Alpaca policy: "+count+" checks passed; no network");
    }
}
