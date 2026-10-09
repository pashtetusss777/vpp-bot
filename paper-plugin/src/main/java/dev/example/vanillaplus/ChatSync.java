package dev.example.vanillaplus;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import io.papermc.paper.advancement.AdvancementDisplay;
import io.papermc.paper.event.player.AsyncChatEvent;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.minimessage.MiniMessage;
import net.kyori.adventure.text.minimessage.tag.resolver.Placeholder;
import net.kyori.adventure.text.minimessage.tag.resolver.TagResolver;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;
import net.kyori.adventure.translation.GlobalTranslator;
import org.bukkit.Bukkit;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.damage.DamageSource;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.event.player.AsyncPlayerChatEvent;
import org.bukkit.event.player.PlayerAdvancementDoneEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.server.ServerLoadEvent;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

public final class ChatSync implements Listener, CommandExecutor {
    private static final int MAX_EVENTS = 500;

    private final VanillaPlusPlusPlugin plugin;
    private final Gson gson;
    private final List<JsonObject> events = new ArrayList<>();
    private final Set<UUID> muted = ConcurrentHashMap.newKeySet();
    private final Path muteFile;
    private final String session = Long.toString(System.currentTimeMillis(), 36);
    private long nextId = 1;
    private volatile long deliveredUpTo = 0;

    public ChatSync(VanillaPlusPlusPlugin plugin, Gson gson) {
        this.plugin = plugin;
        this.gson = gson;
        this.muteFile = plugin.getDataFolder().toPath().resolve("muted-players.txt");
        loadMuted();
    }

    public boolean enabled() {
        return plugin.getConfig().getBoolean("chat-bridge.enabled", true);
    }

    public void register() {
        Bukkit.getPluginManager().registerEvents(this, plugin);
        if (plugin.getCommand("tgbridge") != null) {
            plugin.getCommand("tgbridge").setExecutor(this);
        }
    }

    /** Queues the stop event and waits until the bot has picked it up, at most {@code timeoutMillis}. */
    public void serverStopped(long timeoutMillis) {
        enqueue("server_stop", null, null, null, null, null, false);
        long stopId;
        synchronized (events) {
            stopId = nextId - 1;
        }
        long deadline = System.currentTimeMillis() + timeoutMillis;
        try {
            while (deliveredUpTo < stopId && System.currentTimeMillis() < deadline) {
                Thread.sleep(50);
            }
            if (deliveredUpTo >= stopId) {
                Thread.sleep(300);
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        }
    }

    public String poll(long after) {
        JsonArray batch = new JsonArray();
        synchronized (events) {
            for (JsonObject event : events) {
                long id = event.get("id").getAsLong();
                if (id > after) {
                    batch.add(event);
                    deliveredUpTo = Math.max(deliveredUpTo, id);
                }
            }
            while (events.size() > MAX_EVENTS) {
                events.remove(0);
            }
        }
        JsonObject response = new JsonObject();
        response.addProperty("status", "ok");
        response.addProperty("session", session);
        response.add("events", batch);
        return gson.toJson(response);
    }

    public void broadcast(String sender, String text, String reply) {
        broadcast(sender, text, reply, null, null);
    }

    public void broadcast(String sender, String text, String reply, String formatOverride, String replyOverride) {
        String replyFormat = replyOverride != null && !replyOverride.isBlank()
                ? replyOverride
                : plugin.getConfig().getString("chat-bridge.format.reply", "<gray>[Ответ: <reply>]</gray> ");
        String messageFormat = formatOverride != null && !formatOverride.isBlank()
                ? formatOverride
                : plugin.getConfig().getString(
                        "chat-bridge.format.telegram-message",
                        "<aqua>[TG] <sender>:</aqua> <white><text></white>"
                );
        Component replyPart = Component.empty();
        if (reply != null && !reply.isBlank()) {
            replyPart = miniMessage(replyFormat, Placeholder.unparsed("reply", reply));
        }
        Component message = miniMessage(
                messageFormat,
                Placeholder.component("reply", replyPart),
                Placeholder.unparsed("sender", sender == null ? "Telegram" : sender),
                Placeholder.unparsed("text", text == null ? "" : text)
        );
        if (!messageFormat.contains("<reply>")) {
            message = replyPart.append(message);
        }
        Bukkit.getConsoleSender().sendMessage(message);
        for (Player player : Bukkit.getOnlinePlayers()) {
            if (!muted.contains(player.getUniqueId())) {
                player.sendMessage(message);
            }
        }
    }

    public String tps() {
        double[] tps = Bukkit.getTPS();
        JsonObject response = new JsonObject();
        response.addProperty("status", "ok");
        response.addProperty("tps1m", tps.length > 0 ? tps[0] : 20);
        response.addProperty("tps5m", tps.length > 1 ? tps[1] : 20);
        response.addProperty("tps15m", tps.length > 2 ? tps[2] : 20);
        response.addProperty("mspt", Bukkit.getAverageTickTime());
        return gson.toJson(response);
    }

    @EventHandler
    public void onServerLoad(ServerLoadEvent event) {
        if (enabled()) {
            enqueue("server_start", null, null, null, null, null, false);
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onChat(AsyncChatEvent event) {
        if (!enabled() || incompatiblePrefix() != null || isVanished(event.getPlayer())) {
            return;
        }
        String text = plain(event.message());
        if (!passesMinecraftPrefix(text)) {
            return;
        }
        enqueue("chat", event.getPlayer().getName(), displayName(event.getPlayer()), text, null, null, false);
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = false)
    public void onLegacyChat(AsyncPlayerChatEvent event) {
        String prefix = incompatiblePrefix();
        if (!enabled() || prefix == null || isVanished(event.getPlayer())) {
            return;
        }
        if (!event.getMessage().startsWith(prefix)) {
            return;
        }
        enqueue("chat", event.getPlayer().getName(), displayName(event.getPlayer()), event.getMessage(), null, null, false);
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onJoin(PlayerJoinEvent event) {
        if (!enabled() || isVanished(event.getPlayer())) {
            return;
        }
        enqueue(
                "join",
                event.getPlayer().getName(),
                displayName(event.getPlayer()),
                null,
                null,
                null,
                !event.getPlayer().hasPlayedBefore()
        );
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onQuit(PlayerQuitEvent event) {
        if (!enabled() || isVanished(event.getPlayer())) {
            return;
        }
        enqueue("leave", event.getPlayer().getName(), displayName(event.getPlayer()), null, null, null, false);
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onDeath(PlayerDeathEvent event) {
        if (!enabled() || event.getEntity() == null || isVanished(event.getEntity())) {
            return;
        }
        enqueue(
                "death",
                event.getEntity().getName(),
                displayName(event.getEntity()),
                deathText(event),
                null,
                null,
                false
        );
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onAdvancement(PlayerAdvancementDoneEvent event) {
        if (!enabled() || isVanished(event.getPlayer())) {
            return;
        }
        AdvancementDisplay display = event.getAdvancement().getDisplay();
        if (display == null || !display.doesAnnounceToChat()) {
            return;
        }
        String type = display.frame() == null ? "task" : display.frame().name().toLowerCase(Locale.ROOT);
        enqueue(
                "advancement",
                event.getPlayer().getName(),
                displayName(event.getPlayer()),
                null,
                plain(display.title()),
                plain(display.description()),
                false,
                type
        );
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 1 && args[0].equalsIgnoreCase("reload")) {
            if (!sender.isOp() && !(sender instanceof Player player && player.hasPermission("vanillaplus.tgbridge.reload"))) {
                sender.sendMessage("Нет прав.");
                return true;
            }
            plugin.reloadConfig();
            sender.sendMessage("Конфиг моста перечитан.");
            return true;
        }
        if (args.length == 1 && args[0].equalsIgnoreCase("toggle")) {
            if (!(sender instanceof Player player)) {
                sender.sendMessage("Эту команду может вызвать только игрок.");
                return true;
            }
            if (muted.remove(player.getUniqueId())) {
                sender.sendMessage("Вы будете получать новые сообщения от Telegram.");
            } else {
                muted.add(player.getUniqueId());
                sender.sendMessage("Вы не будете получать новые сообщения от Telegram.");
            }
            saveMuted();
            return true;
        }
        if (args.length >= 4 && args[0].equalsIgnoreCase("send")) {
            if (!sender.isOp() && !(sender instanceof Player player && player.hasPermission("vanillaplus.tgbridge.send"))) {
                sender.sendMessage("Нет прав.");
                return true;
            }
            String format = args[1].toLowerCase(Locale.ROOT);
            if (!format.equals("plain") && !format.equals("html") && !format.equals("mm") && !format.equals("json")) {
                sender.sendMessage("Формат: plain, html, mm или json.");
                return true;
            }
            String text = String.join(" ", java.util.Arrays.copyOfRange(args, 3, args.length));
            JsonObject event = baseEvent("custom");
            event.addProperty("format", format);
            event.addProperty("chat", args[2]);
            event.addProperty("text", text);
            push(event);
            sender.sendMessage("Сообщение поставлено в очередь Telegram.");
            return true;
        }
        sender.sendMessage("Использование: /tgbridge <reload|toggle|send>");
        return true;
    }

    private boolean passesMinecraftPrefix(String text) {
        String prefix = minecraftPrefix();
        return prefix == null || text.startsWith(prefix);
    }

    private String minecraftPrefix() {
        String prefix = plugin.getConfig().getString("chat-bridge.require-prefix-in-minecraft");
        if (prefix == null || prefix.isBlank() || prefix.equalsIgnoreCase("null")) {
            return null;
        }
        return prefix;
    }

    private String incompatiblePrefix() {
        String prefix = plugin.getConfig().getString("chat-bridge.incompatible-plugin-prefix");
        if (prefix == null || prefix.isBlank() || prefix.equalsIgnoreCase("null")) {
            return null;
        }
        return prefix;
    }

    private static boolean isVanished(Player player) {
        return player.hasMetadata("vanished");
    }

    private static String displayName(Player player) {
        return plain(player.displayName());
    }

    private static String deathText(PlayerDeathEvent event) {
        Player player = event.getEntity();
        String rendered = renderDeath(event.deathMessage(), player.locale());
        if (rendered.isBlank()) {
            rendered = renderDeath(event.deathMessage(), Locale.US);
        }
        if (!rendered.isBlank() && !rendered.startsWith("death.")) {
            return rendered;
        }
        String legacy = event.getDeathMessage();
        if (legacy != null && !legacy.isBlank() && !legacy.startsWith("death.")) {
            return legacy;
        }
        return fallbackDeath(player.getName(), event.getDamageSource());
    }

    private static String renderDeath(Component component, Locale locale) {
        if (component == null || locale == null) {
            return "";
        }
        return plain(GlobalTranslator.render(component, locale));
    }

    private static String fallbackDeath(String name, DamageSource source) {
        if (source == null) {
            return name + " погиб";
        }
        Entity killer = source.getCausingEntity();
        String killerName = killer == null ? null : killer.getName();
        String type = source.getDamageType().getKey().getKey();
        return switch (type) {
            case "fall" -> name + " разбился насмерть";
            case "drown" -> name + " утонул";
            case "lava", "in_fire", "on_fire", "hot_floor", "campfire" -> name + " сгорел";
            case "out_of_world" -> name + " выпал из мира";
            case "starve" -> name + " умер от голода";
            case "player_attack", "mob_attack", "mob_attack_no_aggro", "mace_smash", "spear" ->
                    killerName == null ? name + " был убит" : name + " был убит: " + killerName;
            case "arrow", "mob_projectile", "trident", "thrown", "spit" ->
                    killerName == null ? name + " был застрелен" : name + " был застрелен: " + killerName;
            case "explosion", "player_explosion", "bad_respawn_point", "fireworks" -> name + " взорвался";
            case "cactus" -> name + " укололся до смерти";
            case "sweet_berry_bush" -> name + " искололся ягодным кустом";
            case "fly_into_wall" -> name + " испытал кинетическую энергию";
            case "wither" -> name + " иссох";
            case "freeze" -> name + " замёрз насмерть";
            case "cramming" -> name + " был раздавлен";
            case "lightning_bolt" -> name + " был поражён молнией";
            case "magic", "indirect_magic" -> name + " был убит магией";
            case "dragon_breath" -> name + " был обожжён дыханием дракона";
            case "sting" -> name + " был ужален насмерть";
            case "falling_anvil", "falling_block", "falling_stalactite" -> name + " был раздавлен";
            case "stalagmite" -> name + " напоролся на сталагмит";
            default -> killerName == null ? name + " погиб" : name + " был убит: " + killerName;
        };
    }

    private Component miniMessage(String format, TagResolver... resolvers) {
        try {
            return MiniMessage.miniMessage().deserialize(format, resolvers);
        } catch (RuntimeException exception) {
            plugin.getLogger().warning("Неверный формат MiniMessage в chat-bridge.format: " + exception.getMessage());
            return MiniMessage.miniMessage().deserialize("<aqua>[TG] <sender>:</aqua> <white><text></white>", resolvers);
        }
    }

    private static String plain(Component component) {
        if (component == null) {
            return "";
        }
        return PlainTextComponentSerializer.plainText().serialize(component).trim();
    }

    private void enqueue(
            String type,
            String username,
            String display,
            String text,
            String title,
            String description,
            boolean firstJoin
    ) {
        enqueue(type, username, display, text, title, description, firstJoin, null);
    }

    private void enqueue(
            String type,
            String username,
            String display,
            String text,
            String title,
            String description,
            boolean firstJoin,
            String advancementType
    ) {
        JsonObject event = baseEvent(type);
        if (username != null) {
            event.addProperty("username", username);
        }
        if (display != null) {
            event.addProperty("display", display);
        }
        if (text != null) {
            event.addProperty("text", text);
        }
        if (title != null) {
            event.addProperty("title", title);
        }
        if (description != null) {
            event.addProperty("description", description);
        }
        if (advancementType != null) {
            event.addProperty("advancement_type", advancementType);
        }
        event.addProperty("first_join", firstJoin);
        push(event);
    }

    private JsonObject baseEvent(String type) {
        JsonObject event = new JsonObject();
        event.addProperty("type", type);
        return event;
    }

    private void push(JsonObject event) {
        synchronized (events) {
            event.addProperty("id", nextId++);
            event.addProperty("at", System.currentTimeMillis());
            events.add(event);
            while (events.size() > MAX_EVENTS) {
                events.remove(0);
            }
        }
    }

    private void loadMuted() {
        if (!Files.exists(muteFile)) {
            return;
        }
        try {
            for (String line : Files.readAllLines(muteFile, StandardCharsets.UTF_8)) {
                if (!line.isBlank()) {
                    muted.add(UUID.fromString(line.trim()));
                }
            }
        } catch (IOException | IllegalArgumentException exception) {
            plugin.getLogger().warning("Could not read muted players: " + exception.getMessage());
        }
    }

    private void saveMuted() {
        try {
            Files.createDirectories(muteFile.getParent());
            List<String> lines = muted.stream().map(UUID::toString).sorted().toList();
            Files.write(muteFile, lines, StandardCharsets.UTF_8);
        } catch (IOException exception) {
            plugin.getLogger().warning("Could not save muted players: " + exception.getMessage());
        }
    }
}
