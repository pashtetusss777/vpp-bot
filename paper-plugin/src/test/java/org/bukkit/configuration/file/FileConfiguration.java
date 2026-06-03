package org.bukkit.configuration.file;

import java.util.Collections;
import java.util.List;

public class FileConfiguration {
    public String getString(String path, String def) {
        return def;
    }

    public int getInt(String path, int def) {
        return def;
    }

    public boolean getBoolean(String path, boolean def) {
        return def;
    }

    public List<String> getStringList(String path) {
        return Collections.emptyList();
    }
}
