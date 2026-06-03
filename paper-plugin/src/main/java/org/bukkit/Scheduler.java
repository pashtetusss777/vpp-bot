package org.bukkit;

public class Scheduler {
    public void runTask(Object plugin, Runnable r) {
        r.run();
    }
}
