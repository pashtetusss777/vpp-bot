package org.bukkit;

import org.bukkit.entity.Player;
import org.bukkit.plugin.PluginManager;

import java.nio.charset.StandardCharsets;
import java.util.Collection;
import java.util.List;
import java.util.UUID;

public final class Bukkit {
    public static boolean resolveNames = true;
    public static OfflinePlayer lastWhitelisted;

    private static final PluginManager PLUGIN_MANAGER = new PluginManager();
    private static final Scheduler SCHEDULER = new Scheduler();

    public static PluginManager getPluginManager() {
        return PLUGIN_MANAGER;
    }

    public static ConsoleCommandSender getConsoleSender() {
        return new ConsoleCommandSender();
    }

    public static boolean dispatchCommand(ConsoleCommandSender sender, String command) {
        return true;
    }

    public static Scheduler getScheduler() {
        return SCHEDULER;
    }

    public static OfflinePlayer getOfflinePlayer(String name) {
        return new OfflinePlayer(name);
    }

    public static UUID getPlayerUniqueId(String name) {
        if (!resolveNames || name == null || name.isBlank()) {
            return null;
        }
        return UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes(StandardCharsets.UTF_8));
    }

    public static OfflinePlayer getOfflinePlayer(UUID id) {
        lastWhitelisted = new OfflinePlayer(id.toString());
        return lastWhitelisted;
    }

    public static boolean isPrimaryThread() {
        return true;
    }

    public static String getMinecraftVersion() {
        return "26.3";
    }

    public static String getName() {
        return "TestServer";
    }

    public static String getVersion() {
        return "Test Version";
    }

    public static String getBukkitVersion() {
        return "26.3.build.151-beta";
    }

    public static Collection<? extends Player> getOnlinePlayers() {
        return List.of(new Player("Steve"));
    }

    public static Player getPlayerExact(String name) {
        return new Player(name);
    }

    public static int getMaxPlayers() {
        return 20;
    }

    public static boolean hasWhitelist() {
        return true;
    }
}
