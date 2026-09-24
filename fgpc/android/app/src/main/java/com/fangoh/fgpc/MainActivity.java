package com.fangoh.fgpc;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * Thin shell around the Steam Machine WebGUI. Tabs and actions stay on the host.
 */
public class MainActivity extends Activity {
    private WebView web;
    private boolean triedFallback;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        setContentView(web);

        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMediaPlaybackRequiresUserGesture(false);

        web.setWebViewClient(
                new WebViewClient() {
                    @Override
                    public boolean shouldOverrideUrlLoading(
                            WebView view, WebResourceRequest request) {
                        return !isAllowed(request.getUrl() == null ? "" : request.getUrl().getHost());
                    }

                    @Override
                    public void onReceivedError(
                            WebView view, WebResourceRequest request, WebResourceError error) {
                        if (request != null
                                && request.isForMainFrame()
                                && !triedFallback
                                && BuildConfig.FALLBACK_URL != null
                                && !BuildConfig.FALLBACK_URL.isEmpty()) {
                            triedFallback = true;
                            view.loadUrl(BuildConfig.FALLBACK_URL);
                        }
                    }
                });

        String start = BuildConfig.HOME_URL;
        if (getIntent() != null && getIntent().getData() != null) {
            String host = getIntent().getData().getHost();
            if (isAllowed(host)) {
                start = getIntent().getData().toString();
            }
        }
        web.loadUrl(start);
    }

    private static boolean isAllowed(String host) {
        if (host == null) {
            return false;
        }
        return host.equals("fgpc.tailnet.fangoh.dev")
                || host.equals("steammachine.tailnet.fangoh.dev")
                || host.equals("100.64.0.8")
                || host.equals("127.0.0.1");
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.loadUrl("about:blank");
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
