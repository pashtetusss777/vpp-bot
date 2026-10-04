package dev.example.vanillaplus;

public enum Strings {
    PREFIX("[Vanilla++] "),
    DEFAULT_TOKEN("change-this-long-random-secret"),
    CONFIG_PATH("plugins/VanillaPlusPlus/config.yml"),
    BRIDGE_LISTENING("Bridge listening on http://%s:%d"),
    BRIDGE_FAILED("Failed to start HTTP bridge: %s"),
    BRIDGE_STOPPED("Bridge stopped."),
    WHITELIST_ADD_ENDPOINT("/whitelist/add"),
    CONSOLE_EXEC_ENDPOINT("/console/exec"),
    SERVER_STATUS_ENDPOINT("/server/status"),
    SERVER_ONLINE_ENDPOINT("/server/online"),
    PLAYER_INFO_ENDPOINT("/player/info"),
    ERROR_METHOD_NOT_ALLOWED("{\"error\":\"method_not_allowed\"}"),
    ERROR_UNAUTHORIZED("{\"error\":\"unauthorized\"}"),
    ERROR_INVALID_JSON("{\"error\":\"invalid_json\"}"),
    ERROR_INVALID_COMMAND("{\"error\":\"invalid_command\"}"),
    ERROR_FORBIDDEN_COMMAND("{\"error\":\"forbidden_command\"}"),
    ERROR_INVALID_NICKNAME("{\"error\":\"invalid_nickname\"}"),
    ERROR_UNKNOWN_PLAYER("{\"error\":\"unknown_player\"}"),
    ERROR_SERVER_THREAD("{\"error\":\"server_thread\"}"),
    STATUS_OK("{\"status\":\"ok\"}");

    private final String value;

    Strings(String value) {
        this.value = value;
    }

    public String get() {
        return value;
    }
}
