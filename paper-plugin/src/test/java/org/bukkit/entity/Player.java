package org.bukkit.entity;

import java.net.InetSocketAddress;

public class Player {
    private final String name;

    public Player(String name) {
        this.name = name;
    }

    public String getName() {
        return name;
    }

    public InetSocketAddress getAddress() {
        return new InetSocketAddress("127.0.0.1", 25565);
    }
}
