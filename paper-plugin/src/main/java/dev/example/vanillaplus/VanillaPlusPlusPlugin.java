package dev.example.vanillaplus;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParseException;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.OfflinePlayer;
import org.bukkit.plugin.java.JavaPlugin;

import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;

public final class VanillaPlusPlusPlugin extends JavaPlugin {
    private static final Pattern NICKNAME_PATTERN = Pattern.compile("^[A-Za-z0-9_]{3,16}$");
    private static final String PREFIX = ChatColor.BLUE + "[Vanilla++] " + ChatColor.RESET;

    private final Gson gson = new Gson();
    private HttpServer server;
    private ExecutorService executor;
    private String token;

    @Override
    public void onEnable() {
        saveDefaultConfig();

        String host = getConfig().getString("host", "127.0.0.1");
        int port = getConfig().getInt("port", 8088);
        token = getConfig().getString("token", "");

        if (token == null || token.isBlank() || token.equals("change-this-long-random-secret")) {
            console("Set a strong token in plugins/VanillaPlusPlus/config.yml before using the bridge.");
        }

        try {
            server = HttpServer.create(new InetSocketAddress(host, port), 0);
            server.createContext("/whitelist/add", this::handleWhitelistAdd);
            if (getConfig().getBoolean("console.enabled", false)) {
                server.createContext("/console/exec", this::handleConsoleExec);
            }
            executor = Executors.newSingleThreadExecutor();
            server.setExecutor(executor);
            server.start();
            console("Bridge listening on http://" + host + ":" + port);
        } catch (IOException exception) {
            console("Failed to start HTTP bridge: " + exception.getMessage());
            Bukkit.getPluginManager().disablePlugin(this);
        }
    }

    private void handleConsoleExec(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
            sendJson(exchange, 405, "{\"error\":\"method_not_allowed\"}");
            return;
        }

        String authorization = exchange.getRequestHeaders().getFirst("Authorization");
        if (!("Bearer " + token).equals(authorization)) {
            sendJson(exchange, 401, "{\"error\":\"unauthorized\"}");
            return;
        }

        String command;
        try (InputStreamReader reader = new InputStreamReader(exchange.getRequestBody(), StandardCharsets.UTF_8)) {
            JsonObject body = gson.fromJson(reader, JsonObject.class);
            command = body != null && body.has("command") ? body.get("command").getAsString() : "";
        } catch (JsonParseException | IllegalStateException exception) {
            sendJson(exchange, 400, "{\"error\":\"invalid_json\"}");
            return;
        }

        if (command == null || command.isBlank()) {
            sendJson(exchange, 422, "{\"error\":\"invalid_command\"}");
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
            sendJson(exchange, 403, "{\"error\":\"forbidden_command\"}");
            return;
        }

        Bukkit.getScheduler().runTask(this, () -> {
            boolean ok = Bukkit.dispatchCommand(Bukkit.getConsoleSender(), command);
            console("Executed console command: " + command + " => " + (ok ? "ok" : "failed"));
        });

        sendJson(exchange, 200, "{\"status\":\"ok\"}");
    }

    @Override
    public void onDisable() {
        if (server != null) {
            server.stop(1);
        }
        if (executor != null) {
            executor.shutdownNow();
        }
        console("Bridge stopped.");
    }

    private void handleWhitelistAdd(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestMethod().equalsIgnoreCase("POST")) {
            sendJson(exchange, 405, "{\"error\":\"method_not_allowed\"}");
            return;
        }

        String authorization = exchange.getRequestHeaders().getFirst("Authorization");
        if (!("Bearer " + token).equals(authorization)) {
            sendJson(exchange, 401, "{\"error\":\"unauthorized\"}");
            return;
        }

        String nickname;
        try (InputStreamReader reader = new InputStreamReader(exchange.getRequestBody(), StandardCharsets.UTF_8)) {
            JsonObject body = gson.fromJson(reader, JsonObject.class);
            nickname = body != null && body.has("nickname") ? body.get("nickname").getAsString() : "";
        } catch (JsonParseException | IllegalStateException exception) {
            sendJson(exchange, 400, "{\"error\":\"invalid_json\"}");
            return;
        }

        if (!NICKNAME_PATTERN.matcher(nickname).matches()) {
            sendJson(exchange, 422, "{\"error\":\"invalid_nickname\"}");
            return;
        }

        Bukkit.getScheduler().runTask(this, () -> {
            OfflinePlayer player = Bukkit.getOfflinePlayer(nickname);
            player.setWhitelisted(true);
            console("Whitelisted player " + nickname);
        });

        sendJson(exchange, 200, "{\"status\":\"ok\"}");
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
        Bukkit.getConsoleSender().sendMessage(PREFIX + message);
    }
}
