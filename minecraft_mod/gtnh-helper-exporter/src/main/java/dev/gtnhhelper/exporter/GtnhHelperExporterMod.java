package dev.gtnhhelper.exporter;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.server.command.CommandManager;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.text.Text;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.Map;

public final class GtnhHelperExporterMod implements ModInitializer {
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    private static final int SNAPSHOT_SCHEMA_VERSION = 1;

    @Override
    public void onInitialize() {
        CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) ->
            dispatcher.register(CommandManager.literal("gtnhhelper")
                .then(CommandManager.literal("export_inventory")
                    .executes(context -> {
                        if (!(context.getSource().getEntity() instanceof ServerPlayerEntity player)) {
                            context.getSource().sendError(Text.literal("This command can only be run by a player."));
                            return 0;
                        }

                        try {
                            Path written = exportSnapshot(player);
                            player.sendMessage(Text.literal("GTNH Helper snapshot written: " + written.toAbsolutePath()), false);
                            return 1;
                        } catch (IOException ex) {
                            context.getSource().sendError(Text.literal("Failed to write snapshot: " + ex.getMessage()));
                            return 0;
                        }
                    })
                )
            )
        );
    }

    private static Path exportSnapshot(ServerPlayerEntity player) throws IOException {
        Map<String, Long> totals = new HashMap<>();

        for (ItemStack stack : player.getInventory().main) {
            addStack(totals, stack);
        }
        for (ItemStack stack : player.getInventory().armor) {
            addStack(totals, stack);
        }
        for (ItemStack stack : player.getInventory().offHand) {
            addStack(totals, stack);
        }

        JsonArray entries = new JsonArray();
        totals.entrySet().stream()
            .sorted(Map.Entry.comparingByKey())
            .forEach(entry -> {
                JsonObject row = new JsonObject();
                row.addProperty("item_key", entry.getKey());
                row.addProperty("qty_count", entry.getValue());
                entries.add(row);
            });

        JsonObject payload = new JsonObject();
        payload.addProperty("schema_version", SNAPSHOT_SCHEMA_VERSION);
        payload.add("entries", entries);

        String safePlayer = player.getGameProfile().getName().replaceAll("[^a-zA-Z0-9._-]", "_");
        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));

        Path baseDir = player.getServer().getRunDirectory().toPath()
            .resolve("config")
            .resolve("gtnh-helper")
            .resolve("snapshots");
        Files.createDirectories(baseDir);

        Path out = baseDir.resolve(safePlayer + "_" + timestamp + ".json");
        Files.writeString(out, GSON.toJson(payload));
        return out;
    }

    private static void addStack(Map<String, Long> totals, ItemStack stack) {
        if (stack == null || stack.isEmpty()) {
            return;
        }
        String key = Registries.ITEM.getId(stack.getItem()).toString();
        totals.merge(key, (long) stack.getCount(), Long::sum);
    }
}
