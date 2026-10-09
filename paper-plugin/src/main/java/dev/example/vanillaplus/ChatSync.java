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
    private long nextId = 1;

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

    public void serverStopped() {
        enqueue("server_stop", null, null, null, null, null, false);
    }

    public String poll(long after) {
        JsonArray batch = new JsonArray();
        synchronized (events) {
            for (JsonObject event : events) {
                if (event.get("id").getAsLong() > after) {
                    batch.add(event);
                }
            }
            while (events.size() > MAX_EVENTS) {
                events.remove(0);
            }
        }
        JsonObject response = new JsonObject();
        response.addProperty("status", "ok");
        response.add("events", batch);
        return gson.toJson(response);
    }

    public void broadcast(String sender, String text, String reply) {
        String replyFormat = plugin.getConfig().getString(
                "chat-bridge.format.reply",
                "<gray>[ÐžÑ‚Ð²ÐµÑ‚: <reply>]</gray> "
        );
        String messageFormat = plugin.getConfig().getString(
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
                sender.sendMessage("ÐÐµÑ‚ Ð¿Ñ€Ð°Ð².");
                return true;
            }
            plugin.reloadConfig();
            sender.sendMessage("ÐšÐ¾Ð½Ñ„Ð¸Ð³ Ð¼Ð¾ÑÑ‚Ð° Ð¿ÐµÑ€ÐµÑ‡Ð¸Ñ‚Ð°Ð½.");
            return true;
        }
        if (args.length == 1 && args[0].equalsIgnoreCase("toggle")) {
            if (!(sender instanceof Player player)) {
                sender.sendMessage("Ð­Ñ‚Ñƒ ÐºÐ¾Ð¼Ð°Ð½Ð´Ñƒ Ð¼Ð¾Ð¶ÐµÑ‚ Ð²Ñ‹Ð·Ð²Ð°Ñ‚ÑŒ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð¸Ð³Ñ€Ð¾Ðº.");
                return true;
            }
            if (muted.remove(player.getUniqueId())) {
                sender.sendMessage("Ð’Ñ‹ Ð±ÑƒÐ´ÐµÑ‚Ðµ Ð¿Ð¾Ð»ÑƒÑ‡Ð°Ñ‚ÑŒ Ð½Ð¾Ð²Ñ‹Ðµ ÑÐ¾Ð¾Ð±Ñ‰ÐµÐ½Ð¸Ñ Ð¾Ñ‚ Telegram.");
            } else {
                muted.add(player.getUniqueId());
                sender.sendMessage("Ð’Ñ‹ Ð½Ðµ Ð±ÑƒÐ´ÐµÑ‚Ðµ Ð¿Ð¾Ð»ÑƒÑ‡Ð°Ñ‚ÑŒ Ð½Ð¾Ð²Ñ‹Ðµ ÑÐ¾Ð¾Ð±Ñ‰ÐµÐ½Ð¸Ñ Ð¾Ñ‚ Telegram.");
            }
            saveMuted();
            return true;
        }
        if (args.length >= 4 && args[0].equalsIgnoreCase("send")) {
            if (!sender.isOp() && !(sender instanceof Player player && player.hasPermission("vanillaplus.tgbridge.send"))) {
                sender.sendMessage("ÐÐµÑ‚ Ð¿Ñ€Ð°Ð².");
                return true;
            }
            String format = args[1].toLowerCase(Locale.ROOT);
            if (!format.equals("plain") && !format.equals("html") && !format.equals("mm") && !format.equals("json")) {
                sender.sendMessage("Ð¤Ð¾Ñ€Ð¼Ð°Ñ‚: plain, html, mm Ð¸Ð»Ð¸ json.");
                return true;
            }
            String text = String.join(" ", java.util.Arrays.copyOfRange(args, 3, args.length));
            JsonObject event = baseEvent("custom");
            event.addProperty("format", format);
            event.addProperty("chat", args[2]);
            event.addProperty("text", text);
            push(event);
            sender.sendMessage("Ð¡Ð¾Ð¾Ð±Ñ‰ÐµÐ½Ð¸Ðµ Ð¿Ð¾ÑÑ‚Ð°Ð²Ð»ÐµÐ½Ð¾ Ð² Ð¾Ñ‡ÐµÑ€ÐµÐ´ÑŒ Telegram.");
            return true;
        }
        sender.sendMessage("Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ð½Ð¸Ðµ: /tgbridge <reload|toggle|send>");
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
            return name + " Ð¿Ð¾Ð³Ð¸Ð±";
        }
        Entity killer = source.getCausingEntity();
        String killerName = killer == null ? null : killer.getName();
        String type = source.getDamageType().getKey().getKey();
        return switch (type) {
            case "fall" -> name + " Ñ€Ð°Ð·Ð±Ð¸Ð»ÑÑ Ð½Ð°ÑÐ¼ÐµÑ€Ñ‚ÑŒ";
            case "drown" -> name + " ÑƒÑ‚Ð¾Ð½ÑƒÐ»";
            case "lava", "in_fire", "on_fire", "hot_floor", "campfire" -> name + " ÑÐ³Ð¾Ñ€ÐµÐ»";
            case "out_of_world" -> name + " Ð²Ñ‹Ð¿Ð°Ð» Ð¸Ð· Ð¼Ð¸Ñ€Ð°";
            case "starve" -> name + " ÑƒÐ¼ÐµÑ€ Ð¾Ñ‚ Ð³Ð¾Ð»Ð¾Ð´Ð°";
            case "player_attack", "mob_attack", "mob_attack_no_aggro", "mace_smash", "spear" ->
                    killerName == null ? name + " Ð±Ñ‹Ð» ÑƒÐ±Ð¸Ñ‚" : name + " Ð±Ñ‹Ð» ÑƒÐ±Ð¸Ñ‚: " + killerName;
            case "arrow", "mob_projectile", "trident", "thrown", "spit" ->
                    killerName == null ? name + " Ð±Ñ‹Ð» Ð·Ð°ÑÑ‚Ñ€ÐµÐ»ÐµÐ½" : name + " Ð±Ñ‹Ð» Ð·Ð°ÑÑ‚Ñ€ÐµÐ»ÐµÐ½: " + killerName;
            case "explosion", "player_explosion", "bad_respawn_point", "fireworks" -> name + " Ð²Ð·Ð¾Ñ€Ð²Ð°Ð»ÑÑ";
            case "cactus" -> name + " ÑƒÐºÐ¾Ð»Ð¾Ð»ÑÑ Ð´Ð¾ ÑÐ¼ÐµÑ€Ñ‚Ð¸";
            case "sweet_berry_bush" -> name + " Ð¸ÑÐºÐ¾Ð»Ð¾Ð»ÑÑ ÑÐ³Ð¾Ð´Ð½Ñ‹Ð¼ ÐºÑƒÑÑ‚Ð¾Ð¼";
            case "fly_into_wall" -> name + " Ð¸ÑÐ¿Ñ‹Ñ‚Ð°Ð» ÐºÐ¸Ð½ÐµÑ‚Ð¸Ñ‡ÐµÑÐºÑƒÑŽ ÑÐ½ÐµÑ€Ð³Ð¸ÑŽ";
            case "wither" -> name + " Ð¸ÑÑÐ¾Ñ…";
            case "freeze" -> name + " Ð·Ð°Ð¼Ñ‘Ñ€Ð· Ð½Ð°ÑÐ¼ÐµÑ€Ñ‚ÑŒ";
            case "cramming" -> name + " Ð±Ñ‹Ð» Ñ€Ð°Ð·Ð´Ð°Ð²Ð»ÐµÐ½";
            case "lightning_bolt" -> name + " Ð±Ñ‹Ð» Ð¿Ð¾Ñ€Ð°Ð¶Ñ‘Ð½ Ð¼Ð¾Ð»Ð½Ð¸ÐµÐ¹";
            case "magic", "indirect_magic" -> name + " Ð±Ñ‹Ð» ÑƒÐ±Ð¸Ñ‚ Ð¼Ð°Ð³Ð¸ÐµÐ¹";
            case "dragon_breath" -> name + " Ð±Ñ‹Ð» Ð¾Ð±Ð¾Ð¶Ð¶Ñ‘Ð½ Ð´Ñ‹Ñ…Ð°Ð½Ð¸ÐµÐ¼ Ð´Ñ€Ð°ÐºÐ¾Ð½Ð°";
            case "sting" -> name + " Ð±Ñ‹Ð» ÑƒÐ¶Ð°Ð»ÐµÐ½ Ð½Ð°ÑÐ¼ÐµÑ€Ñ‚ÑŒ";
            case "falling_anvil", "falling_block", "falling_stalactite" -> name + " Ð±Ñ‹Ð» Ñ€Ð°Ð·Ð´Ð°Ð²Ð»ÐµÐ½";
            case "stalagmite" -> name + " Ð½Ð°Ð¿Ð¾Ñ€Ð¾Ð»ÑÑ Ð½Ð° ÑÑ‚Ð°Ð»Ð°Ð³Ð¼Ð¸Ñ‚";
            default -> killerName == null ? name + " Ð¿Ð¾Ð³Ð¸Ð±" : name + " Ð±Ñ‹Ð» ÑƒÐ±Ð¸Ñ‚: " + killerName;
        };
    }

    private Component miniMessage(String format, TagResolver... resolvers) {
        try {
            return MiniMessage.miniMessage().deserialize(format, resolvers);
        } catch (RuntimeException exception) {
            plugin.getLogger().warning("ÐÐµÐ²ÐµÑ€Ð½Ñ‹Ð¹ Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚ MiniMessage Ð² chat-bridge.format: " + exception.getMessage());
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
