package dev.example.vanillaplus;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParseException;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.bukkit.Bukkit;
import org.bukkit.OfflinePlayer;
import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;

import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.regex.Pattern;

public final class VanillaPlusPlusPlugin extends JavaPlugin {
    private static final Pattern NICKNAME_PATTERN = Pattern.compile("^[A-Za-z0-9_]{3,16}$");

    private final Gson gson = new Gson();
    private HttpServer server;
    private ExecutorService executor;
    private String token;
    private ChatSync chatSync;

    @Override
    public void onEnable() {
        saveDefaultConfig();

        String host = getConfig().getString("host", "127.0.0.1");
        int port = getConfig().getInt("port", 8088);
        token = getConfig().getString("token", "");

        if (token == null || token.isBlank() || token.equals(Strings.DEFAULT_TOKEN.get())) {
            console("Set a strong token in " + Strings.CONFIG_PATH.get() + " before using the bridge.");
        }

        try {
            server = HttpServer.create(new InetSocketAddress(host, port), 0);
            server.createContext(Strings.WHITELIST_ADD_ENDPOINT.get(), this::handleWhitelistAdd);
            server.createContext(Strings.SERVER_STATUS_ENDPOINT.get(), this::handleServerStatus);
            server.createContext(Strings.SERVER_ONLINE_ENDPOINT.get(), this::handleServerOnline);
            server.createContext(Strings.PLAYER_INFO_ENDPOINT.get(), this::handlePlayerInfo);
            if (getConfig().getBoolean("console.enabled", false)) {
                server.createContext(Strings.CONSOLE_EXEC_ENDPOINT.get(), this::handleConsoleExec);
            }
            chatSync = new ChatSync(this, gson);
            chatSync.register();
            server.createContext(Strings.CHAT_EVENTS_ENDPOINT.get(), this::handleChatEvents);
            server.createContext(Strings.CHAT_BROADCAST_ENDPOINT.get(), this::handleChatBroadcast);
            server.createContext(Strings.CHAT_TPS_ENDPOINT.get(), this::handleChatTps);
            executor = Executors.newSingleThreadExecutor();
            server.setExecutor(executor);
            server.start();
            console(String.format(Strings.BRIDGE_LISTENING.get(), host, port));
        } catch (IOException exception) {
            console(String.format(Strings.BRIDGE_FAILED.get(), exception.getMessage()));
            Bukkit.getPluginManager().disablePlugin(this);
        }
    }

    private void handleConsoleExec(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
            sendJson(exchange, 405, Strings.ERROR_METHOD_NOT_ALLOWED.get());
            return;
        }

        if (!isAuthorized(exchange)) {
            sendJson(exchange, 401, Strings.ERROR_UNAUTHORIZED.get());
            return;
        }

        String command;
        try (InputStreamReader reader = new InputStreamReader(exchange.getRequestBody(), StandardCharsets.UTF_8)) {
            JsonObject body = gson.fromJson(reader, JsonObject.class);
            command = body != null && body.has("command") ? body.get("command").getAsString() : "";
        } catch (JsonParseException | IllegalStateException exception) {
            sendJson(exchange, 400, Strings.ERROR_INVALID_JSON.get());
            return;
        }

        if (command == null || command.isBlank()) {
            sendJson(exchange, 422, Strings.ERROR_INVALID_COMMAND.get());
            return;
        }

        List<String> allowed = getConfig().getStringList("console.allowed-commands");
        boolean allowedToRun = false;
        if (allowed != null && !allowed.isEmpty()) {
            String lower = command.toLowerCase();
            for (String a : allowed) {
                String p = a == null ? "" : a.trim().toLowerCase();
                if (p.equals("*") || lower.equals(p) || lower.startsWith(p + " ")) {
                    allowedToRun = true;
                    break;
                }
            }
        }

        if (!allowedToRun) {
            sendJson(exchange, 403, Strings.ERROR_FORBIDDEN_COMMAND.get());
            return;
        }

        final boolean ok;
        try {
            ok = callOnServerThread(() -> dispatchConsole(command));
        } catch (Exception exception) {
            console("Console command failed: " + exception.getMessage());
            sendJson(exchange, 500, Strings.ERROR_SERVER_THREAD.get());
            return;
        }

        JsonObject response = new JsonObject();
        response.addProperty("status", "ok");
        response.addProperty("ok", ok);
        response.addProperty("command", command);
        sendJson(exchange, 200, gson.toJson(response));
    }

    private boolean dispatchConsole(String command) {
        boolean ok = Bukkit.dispatchCommand(Bukkit.getConsoleSender(), command);
        console("Executed console command: " + command + " => " + (ok ? "ok" : "failed"));
        return ok;
    }

    @Override
    public void onDisable() {
        if (chatSync != null && chatSync.enabled()) {
            chatSync.serverStopped();
            try {
                Thread.sleep(1200);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
            }
        }
        if (server != null) {
            server.stop(1);
        }
        if (executor != null) {
            executor.shutdownNow();
        }
        console(Strings.BRIDGE_STOPPED.get());
    }

    private void handleChatEvents(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestMethod().equalsIgnoreCase("GET")) {
            sendJson(exchange, 405, Strings.ERROR_METHOD_NOT_ALLOWED.get());
            return;
        }
        if (!isAuthorized(exchange)) {
            sendJson(exchange, 401, Strings.ERROR_UNAUTHORIZED.get());
            return;
        }
        long after = 0;
        String rawAfter = getQueryParam(exchange, "after");
        if (rawAfter != null && !rawAfter.isBlank()) {
            try {
                after = Long.parseLong(rawAfter);
            } catch (NumberFormatException exception) {
                sendJson(exchange, 422, Strings.ERROR_INVALID_JSON.get());
                return;
            }
        }
        sendJson(exchange, 200, chatSync.poll(after));
    }

    private void handleChatBroadcast(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
            sendJson(exchange, 405, Strings.ERROR_METHOD_NOT_ALLOWED.get());
            return;
        }
        if (!isAuthorized(exchange)) {
            sendJson(exchange, 401, Strings.ERROR_UNAUTHORIZED.get());
            return;
        }
        String sender;
        String text;
        String reply;
        try (InputStreamReader reader = new InputStreamReader(exchange.getRequestBody(), StandardCharsets.UTF_8)) {
            JsonObject body = gson.fromJson(reader, JsonObject.class);
            sender = body != null && body.has("sender") ? body.get("sender").getAsString() : "";
            text = body != null && body.has("text") ? body.get("text").getAsString() : "";
            reply = body != null && body.has("reply") && !body.get("reply").isJsonNull()
                    ? body.get("reply").getAsString()
                    : "";
        } catch (JsonParseException | IllegalStateException exception) {
            sendJson(exchange, 400, Strings.ERROR_INVALID_JSON.get());
            return;
        }
        if (sender.isBlank() || text.isBlank()) {
            sendJson(exchange, 422, Strings.ERROR_INVALID_JSON.get());
            return;
        }
        final String from = sender;
        final String message = text;
        final String quoted = reply;
        try {
            callOnServerThread(() -> {
                chatSync.broadcast(from, message, quoted);
                return true;
            });
        } catch (Exception exception) {
            console("Chat broadcast failed: " + exception.getMessage());
            sendJson(exchange, 500, Strings.ERROR_SERVER_THREAD.get());
            return;
        }
        sendJson(exchange, 200, Strings.STATUS_OK.get());
    }

    private void handleChatTps(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestMethod().equalsIgnoreCase("GET")) {
            sendJson(exchange, 405, Strings.ERROR_METHOD_NOT_ALLOWED.get());
            return;
        }
        if (!isAuthorized(exchange)) {
            sendJson(exchange, 401, Strings.ERROR_UNAUTHORIZED.get());
            return;
        }
        final String body;
        try {
            body = callOnServerThread(chatSync::tps);
        } catch (Exception exception) {
            console("TPS query failed: " + exception.getMessage());
            sendJson(exchange, 500, Strings.ERROR_SERVER_THREAD.get());
            return;
        }
        sendJson(exchange, 200, body);
    }

    private void handleWhitelistAdd(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
            sendJson(exchange, 405, Strings.ERROR_METHOD_NOT_ALLOWED.get());
            return;
        }

        if (!isAuthorized(exchange)) {
            sendJson(exchange, 401, Strings.ERROR_UNAUTHORIZED.get());
            return;
        }

        String nickname;
        try (InputStreamReader reader = new InputStreamReader(exchange.getRequestBody(), StandardCharsets.UTF_8)) {
            JsonObject body = gson.fromJson(reader, JsonObject.class);
            nickname = body != null && body.has("nickname") ? body.get("nickname").getAsString() : "";
        } catch (JsonParseException | IllegalStateException exception) {
            sendJson(exchange, 400, Strings.ERROR_INVALID_JSON.get());
            return;
        }

        if (!NICKNAME_PATTERN.matcher(nickname).matches()) {
            sendJson(exchange, 422, Strings.ERROR_INVALID_NICKNAME.get());
            return;
        }

        final boolean added;
        try {
            added = callOnServerThread(() -> whitelistPlayer(nickname));
        } catch (Exception exception) {
            console("Whitelist add failed for " + nickname + ": " + exception.getMessage());
            sendJson(exchange, 500, Strings.ERROR_SERVER_THREAD.get());
            return;
        }
        if (!added) {
            sendJson(exchange, 404, Strings.ERROR_UNKNOWN_PLAYER.get());
            return;
        }

        sendJson(exchange, 200, Strings.STATUS_OK.get());
    }

    private boolean whitelistPlayer(String nickname) {
        UUID uniqueId = Bukkit.getPlayerUniqueId(nickname);
        if (uniqueId == null) {
            return false;
        }
        OfflinePlayer player = Bukkit.getOfflinePlayer(uniqueId);
        player.setWhitelisted(true);
        console("Whitelisted player " + nickname);
        return true;
    }

    private void handleServerStatus(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestMethod().equalsIgnoreCase("GET")) {
            sendJson(exchange, 405, Strings.ERROR_METHOD_NOT_ALLOWED.get());
            return;
        }

        if (!isAuthorized(exchange)) {
            sendJson(exchange, 401, Strings.ERROR_UNAUTHORIZED.get());
            return;
        }

        final String body;
        try {
            body = callOnServerThread(this::buildServerStatusJson);
        } catch (Exception exception) {
            console("Server status failed: " + exception.getMessage());
            sendJson(exchange, 500, Strings.ERROR_SERVER_THREAD.get());
            return;
        }
        sendJson(exchange, 200, body);
    }

    private String buildServerStatusJson() {
        JsonObject response = new JsonObject();
        response.addProperty("status", "ok");
        response.addProperty("name", Bukkit.getName());
        response.addProperty("version", Bukkit.getVersion());
        response.addProperty("minecraft_version", Bukkit.getMinecraftVersion());
        response.addProperty("bukkit_version", Bukkit.getBukkitVersion());
        response.addProperty("online", Bukkit.getOnlinePlayers().size());
        response.addProperty("max_players", Bukkit.getMaxPlayers());
        response.addProperty("whitelist", Bukkit.hasWhitelist());
        response.addProperty("console_enabled", getConfig().getBoolean("console.enabled", false));
        return gson.toJson(response);
    }

    private void handleServerOnline(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestMethod().equalsIgnoreCase("GET")) {
            sendJson(exchange, 405, Strings.ERROR_METHOD_NOT_ALLOWED.get());
            return;
        }

        if (!isAuthorized(exchange)) {
            sendJson(exchange, 401, Strings.ERROR_UNAUTHORIZED.get());
            return;
        }

        final String body;
        try {
            body = callOnServerThread(this::buildOnlineJson);
        } catch (Exception exception) {
            console("Online list failed: " + exception.getMessage());
            sendJson(exchange, 500, Strings.ERROR_SERVER_THREAD.get());
            return;
        }
        sendJson(exchange, 200, body);
    }

    private String buildOnlineJson() {
        List<String> players = new ArrayList<>();
        for (Player player : Bukkit.getOnlinePlayers()) {
            players.add(player.getName());
        }
        JsonObject response = new JsonObject();
        response.addProperty("status", "ok");
        response.addProperty("online", players.size());
        response.addProperty("max_players", Bukkit.getMaxPlayers());
        response.add("players", gson.toJsonTree(players));
        return gson.toJson(response);
    }

    private void handlePlayerInfo(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestMethod().equalsIgnoreCase("GET")) {
            sendJson(exchange, 405, Strings.ERROR_METHOD_NOT_ALLOWED.get());
            return;
        }

        if (!isAuthorized(exchange)) {
            sendJson(exchange, 401, Strings.ERROR_UNAUTHORIZED.get());
            return;
        }

        String nickname = getQueryParam(exchange, "name");
        if (nickname == null || !NICKNAME_PATTERN.matcher(nickname).matches()) {
            sendJson(exchange, 422, Strings.ERROR_INVALID_NICKNAME.get());
            return;
        }

        final String body;
        try {
            body = callOnServerThread(() -> buildPlayerInfoJson(nickname));
        } catch (Exception exception) {
            console("Player info failed for " + nickname + ": " + exception.getMessage());
            sendJson(exchange, 500, Strings.ERROR_SERVER_THREAD.get());
            return;
        }
        sendJson(exchange, 200, body);
    }

    private String buildPlayerInfoJson(String nickname) {
        Player player = Bukkit.getPlayerExact(nickname);
        JsonObject response = new JsonObject();
        response.addProperty("status", "ok");
        response.addProperty("name", nickname);
        response.addProperty("online", player != null);
        if (player != null && player.getAddress() != null) {
            InetSocketAddress address = player.getAddress();
            response.addProperty("ip", address.getAddress().getHostAddress());
            response.addProperty("port", address.getPort());
        }
        return gson.toJson(response);
    }

    private <T> T callOnServerThread(Callable<T> task) throws Exception {
        if (Bukkit.isPrimaryThread()) {
            return task.call();
        }

        CompletableFuture<T> future = new CompletableFuture<>();
        Bukkit.getScheduler().runTask(this, () -> {
            try {
                future.complete(task.call());
            } catch (Throwable throwable) {
                future.completeExceptionally(throwable);
            }
        });
        try {
            return future.get(4, TimeUnit.SECONDS);
        } catch (TimeoutException exception) {
            throw new IOException("Timed out waiting for the server thread", exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IOException("Interrupted while waiting for the server thread", exception);
        } catch (ExecutionException exception) {
            Throwable cause = exception.getCause() == null ? exception : exception.getCause();
            if (cause instanceof Exception checked) {
                throw checked;
            }
            throw new IOException(cause);
        }
    }

    private String getQueryParam(HttpExchange exchange, String name) {
        String query = exchange.getRequestURI().getRawQuery();
        if (query == null || query.isBlank()) {
            return null;
        }
        for (String part : query.split("&")) {
            String[] pair = part.split("=", 2);
            String key = URLDecoder.decode(pair[0], StandardCharsets.UTF_8);
            if (key.equals(name)) {
                return pair.length > 1 ? URLDecoder.decode(pair[1], StandardCharsets.UTF_8) : "";
            }
        }
        return null;
    }

    private boolean isAuthorized(HttpExchange exchange) {
        String authorization = exchange.getRequestHeaders().getFirst("Authorization");
        return ("Bearer " + token).equals(authorization);
    }

    private void sendJson(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }

    private void console(String message) {
        getLogger().info(message);
    }
}
