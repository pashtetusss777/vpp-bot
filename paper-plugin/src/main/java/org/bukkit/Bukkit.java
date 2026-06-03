package org.bukkit;

import org.bukkit.plugin.PluginManager;

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
}
