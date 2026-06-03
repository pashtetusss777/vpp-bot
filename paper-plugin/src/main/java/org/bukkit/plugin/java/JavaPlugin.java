package org.bukkit.plugin.java;

import org.bukkit.configuration.file.FileConfiguration;

public class JavaPlugin {
    private final FileConfiguration config = new FileConfiguration();

    public void saveDefaultConfig() {
        // no-op
    }

    public FileConfiguration getConfig() {
        return config;
    }

    public void onEnable() {
        // no-op
    }

    public void onDisable() {
        // no-op
    }
}
