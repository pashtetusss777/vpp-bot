package dev.example.vanillaplus;

import com.google.gson.Gson;
import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpContext;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpPrincipal;
import org.junit.jupiter.api.Test;

import java.io.*;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.net.URI;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class VanillaPlusPlusPluginHandlersTest {

    static class MockHttpExchange extends HttpExchange {
        private final Headers reqHeaders = new Headers();
        private final Headers respHeaders = new Headers();
        private final ByteArrayOutputStream respBody = new ByteArrayOutputStream();
        private final InputStream reqBody;
        private final String method;
        private final Map<String, Object> attributes = new HashMap<>();
        private int status = -1;

        MockHttpExchange(String method, String body) {
            this.method = method;
            this.reqBody = new ByteArrayInputStream(body == null ? new byte[0] : body.getBytes());
        }

        @Override
        public Headers getRequestHeaders() {
            return reqHeaders;
        }

        @Override
        public Headers getResponseHeaders() {
            return respHeaders;
        }

        @Override
        public URI getRequestURI() {
            return URI.create("/");
        }

        @Override
        public String getRequestMethod() {
            return method;
        }

        @Override
        public HttpContext getHttpContext() {
            return null;
        }

        @Override
        public void close() {
        }

        @Override
        public InputStream getRequestBody() {
            return reqBody;
        }

        @Override
        public OutputStream getResponseBody() {
            return respBody;
        }

        @Override
        public void sendResponseHeaders(int rCode, long responseLength) throws IOException {
            this.status = rCode;
        }

        @Override
        public InetSocketAddress getRemoteAddress() {
            return new InetSocketAddress(0);
        }

        @Override
        public void setStreams(InputStream i, OutputStream o) {
            // no-op for test
        }

        @Override
        public HttpPrincipal getPrincipal() {
            return null;
        }

        @Override
        public InetSocketAddress getLocalAddress() {
            return new InetSocketAddress(0);
        }

        @Override
        public String getProtocol() {
            return "HTTP/1.1";
        }

        @Override
        public Object getAttribute(String name) {
            return attributes.get(name);
        }

        @Override
        public void setAttribute(String name, Object value) {
            attributes.put(name, value);
        }

        @Override
        public int getResponseCode() {
            return status;
        }

        int getStatus() {
            return status;
        }

        String getResponseBodyString() {
            return respBody.toString();
        }
    }

    private void setToken(VanillaPlusPlusPlugin plugin, String value) throws Exception {
        Field tokenField = VanillaPlusPlusPlugin.class.getDeclaredField("token");
        tokenField.setAccessible(true);
        tokenField.set(plugin, value);
    }

    @Test
    void consoleExec_methodNotAllowed_returns405() throws Exception {
        VanillaPlusPlusPlugin plugin = new VanillaPlusPlusPlugin();
        MockHttpExchange ex = new MockHttpExchange("GET", null);

        Method m = VanillaPlusPlusPlugin.class.getDeclaredMethod("handleConsoleExec", HttpExchange.class);
        m.setAccessible(true);
        m.invoke(plugin, ex);

        assertEquals(405, ex.getStatus());
        assertEquals(Strings.ERROR_METHOD_NOT_ALLOWED.get(), ex.getResponseBodyString());
    }

    @Test
    void consoleExec_unauthorized_returns401() throws Exception {
        VanillaPlusPlusPlugin plugin = new VanillaPlusPlusPlugin();
        setToken(plugin, "secret");
        MockHttpExchange ex = new MockHttpExchange("POST", "{}");

        Method m = VanillaPlusPlusPlugin.class.getDeclaredMethod("handleConsoleExec", HttpExchange.class);
        m.setAccessible(true);
        m.invoke(plugin, ex);

        assertEquals(401, ex.getStatus());
        assertEquals(Strings.ERROR_UNAUTHORIZED.get(), ex.getResponseBodyString());
    }

    @Test
    void consoleExec_invalidJson_returns400() throws Exception {
        VanillaPlusPlusPlugin plugin = new VanillaPlusPlusPlugin();
        setToken(plugin, "secret");
        MockHttpExchange ex = new MockHttpExchange("POST", "{badjson");
        ex.getRequestHeaders().add("Authorization", "Bearer secret");

        Method m = VanillaPlusPlusPlugin.class.getDeclaredMethod("handleConsoleExec", HttpExchange.class);
        m.setAccessible(true);
        m.invoke(plugin, ex);

        assertEquals(400, ex.getStatus());
        assertEquals(Strings.ERROR_INVALID_JSON.get(), ex.getResponseBodyString());
    }

    @Test
    void whitelistAdd_invalidNickname_returns422() throws Exception {
        VanillaPlusPlusPlugin plugin = new VanillaPlusPlusPlugin();
        setToken(plugin, "secret");
        MockHttpExchange ex = new MockHttpExchange("POST", new Gson().toJson(java.util.Map.of("nickname", "bad nick")));
        ex.getRequestHeaders().add("Authorization", "Bearer secret");

        Method m = VanillaPlusPlusPlugin.class.getDeclaredMethod("handleWhitelistAdd", HttpExchange.class);
        m.setAccessible(true);
        m.invoke(plugin, ex);

        assertEquals(422, ex.getStatus());
        assertEquals(Strings.ERROR_INVALID_NICKNAME.get(), ex.getResponseBodyString());
    }

    @Test
    void whitelistAdd_unknownPlayer_returns404() throws Exception {
        org.bukkit.Bukkit.resolveNames = false;
        org.bukkit.Bukkit.lastWhitelisted = null;
        try {
            VanillaPlusPlusPlugin plugin = new VanillaPlusPlusPlugin();
            setToken(plugin, "secret");
            MockHttpExchange ex = new MockHttpExchange("POST", new Gson().toJson(java.util.Map.of("nickname", "Steve")));
            ex.getRequestHeaders().add("Authorization", "Bearer secret");

            Method m = VanillaPlusPlusPlugin.class.getDeclaredMethod("handleWhitelistAdd", HttpExchange.class);
            m.setAccessible(true);
            m.invoke(plugin, ex);

            assertEquals(404, ex.getStatus());
            assertEquals(Strings.ERROR_UNKNOWN_PLAYER.get(), ex.getResponseBodyString());
            assertNull(org.bukkit.Bukkit.lastWhitelisted);
        } finally {
            org.bukkit.Bukkit.resolveNames = true;
        }
    }

    @Test
    void whitelistAdd_resolvedPlayer_whitelistsUuid() throws Exception {
        org.bukkit.Bukkit.resolveNames = true;
        org.bukkit.Bukkit.lastWhitelisted = null;
        VanillaPlusPlusPlugin plugin = new VanillaPlusPlusPlugin();
        setToken(plugin, "secret");
        MockHttpExchange ex = new MockHttpExchange("POST", new Gson().toJson(java.util.Map.of("nickname", "Steve")));
        ex.getRequestHeaders().add("Authorization", "Bearer secret");

        Method m = VanillaPlusPlusPlugin.class.getDeclaredMethod("handleWhitelistAdd", HttpExchange.class);
        m.setAccessible(true);
        m.invoke(plugin, ex);

        assertEquals(200, ex.getStatus());
        assertEquals(Strings.STATUS_OK.get(), ex.getResponseBodyString());
        assertNotNull(org.bukkit.Bukkit.lastWhitelisted);
        assertTrue(org.bukkit.Bukkit.lastWhitelisted.isWhitelisted());
    }

    @Test
    void serverStatus_includesMinecraftVersion() throws Exception {
        VanillaPlusPlusPlugin plugin = new VanillaPlusPlusPlugin();
        setToken(plugin, "secret");
        MockHttpExchange ex = new MockHttpExchange("GET", null);
        ex.getRequestHeaders().add("Authorization", "Bearer secret");

        Method m = VanillaPlusPlusPlugin.class.getDeclaredMethod("handleServerStatus", HttpExchange.class);
        m.setAccessible(true);
        m.invoke(plugin, ex);

        assertEquals(200, ex.getStatus());
        assertTrue(ex.getResponseBodyString().contains("\"minecraft_version\":\"26.3\""));
    }
}
