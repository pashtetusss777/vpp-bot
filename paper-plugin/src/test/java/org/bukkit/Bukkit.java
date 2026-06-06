package org.bukkit;

import org.bukkit.entity.Player;
import org.bukkit.plugin.PluginManager;

import java.util.Collection;
import java.util.List;

public final class Bukkit {
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

    public static String getName() {
        return "TestServer";
    }

    public static String getVersion() {
        return "Test Version";
    }

    public static String getBukkitVersion() {
        return "1.21.3-R0.1-SNAPSHOT";
    }

    public static Collection<? extends Player> getOnlinePlayers() {
        return List.of(new Player("Steve"));
    }

    public static int getMaxPlayers() {
        return 20;
    }

    public static boolean hasWhitelist() {
        return true;
    }
}
