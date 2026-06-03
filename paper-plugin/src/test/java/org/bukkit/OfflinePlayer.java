package org.bukkit;

public class OfflinePlayer {
    private final String name;
    private boolean whitelisted = false;

    public OfflinePlayer(String name) {
        this.name = name;
    }

    public void setWhitelisted(boolean value) {
        this.whitelisted = value;
    }

    public boolean isWhitelisted() {
        return whitelisted;
    }

    public String getName() {
        return name;
    }
}
