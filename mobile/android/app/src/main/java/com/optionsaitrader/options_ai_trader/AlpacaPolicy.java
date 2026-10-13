package com.optionsaitrader.options_ai_trader;

import java.net.URI;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.List;

/** Data-only boundary. No configurable host, trading endpoint or arbitrary payload. */
public final class AlpacaPolicy {
    private AlpacaPolicy() {}
    public static boolean symbol(String s) { return s != null && s.matches("[A-Z][A-Z0-9.]{0,9}"); }
    public static boolean contract(String s) { return s != null && s.matches("[A-Z]{1,6}[0-9]{6}[CP][0-9]{8}"); }
    public static boolean feed(String s) { return "iex".equals(s) || "sip".equals(s); }
    public static boolean permits(String method, String raw) {
        try {
            URI u = URI.create(raw);
            if (!"GET".equals(method) || u.getUserInfo() != null || u.getFragment() != null || u.getPort() != -1) return false;
            String path=u.getRawPath();
            if ("https".equals(u.getScheme()) && "data.alpaca.markets".equals(u.getHost()))
                return "/v2/stocks/bars".equals(path) || "/v1beta1/options/snapshots".equals(path);
            return "https".equals(u.getScheme()) && "stream.data.alpaca.markets".equals(u.getHost()) &&
                ("/v2/iex".equals(path) || "/v2/sip".equals(path)) && u.getRawQuery() == null;
        } catch (Exception e) { return false; }
    }
    public static boolean inSession(long epochMs, String session) {
        ZonedDateTime t=Instant.ofEpochMilli(epochMs).atZone(ZoneId.of("America/New_York"));
        int day=t.getDayOfWeek().getValue(), minute=t.getHour()*60+t.getMinute();
        if (day>5) return false;
        return "regular".equals(session) ? minute>=570 && minute<960 :
            "extended".equals(session) && minute>=240 && minute<1200;
    }
    public static boolean freshBar(long start, long now) { return start+60000<=now && now-start<=150000; }
    public static boolean terminal(int code) { return code==401 || code==402 || code==403 || code==405 || code==406 || code==407 || code==409; }
    public static long retryMs(int attempt) { return Math.min(120000L, 5000L << Math.min(5, Math.max(0,attempt))); }
    public static boolean validBar(double o,double h,double l,double c,double v) {
        return Double.isFinite(o)&&Double.isFinite(h)&&Double.isFinite(l)&&Double.isFinite(c)&&Double.isFinite(v)&&
            l>0 && h>=Math.max(o,c) && l<=Math.min(o,c) && v>=0;
    }
    /** Same rolling RSI definition as the existing Flutter chart lab. */
    public static Double rsi(List<Double> c) {
        if(c.size()<15) return null;
        double gain=0,loss=0;
        for(int i=c.size()-14;i<c.size();i++){double d=c.get(i)-c.get(i-1);gain+=Math.max(0,d);loss+=Math.max(0,-d);}
        return gain+loss==0 ? 50.0 : loss==0 ? 100.0 : 100-100/(1+gain/loss);
    }
    public static Double macd(List<Double> c) {
        if(c.size()<26)return null;
        double fast=c.get(0),slow=fast;
        for(int i=1;i<c.size();i++){fast+=2.0/13*(c.get(i)-fast);slow+=2.0/27*(c.get(i)-slow);}
        return fast-slow;
    }
}
