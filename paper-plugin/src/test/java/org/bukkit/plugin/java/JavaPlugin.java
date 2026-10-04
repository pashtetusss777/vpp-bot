package org.bukkit.plugin.java;

import org.bukkit.configuration.file.FileConfiguration;

import java.util.logging.Logger;

public class JavaPlugin {
    private final FileConfiguration config = new FileConfiguration();

    public void saveDefaultConfig() {
        // no-op
    }

    public FileConfiguration getConfig() {
        return config;
    }

    public Logger getLogger() {
        return Logger.getLogger("VanillaPlusPlusTest");
    }

    public void onEnable() {
        // no-op
    }

    public void onDisable() {
        // no-op
    }
}
