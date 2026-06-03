package org.bukkit;

public class Scheduler {
    public void runTask(Object plugin, Runnable r) {
        // For tests run immediately
        r.run();
    }
}
