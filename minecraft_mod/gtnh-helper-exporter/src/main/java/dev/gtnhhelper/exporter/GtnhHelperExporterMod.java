package dev.gtnhhelper.exporter;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.recipe.Ingredient;
import net.minecraft.recipe.Recipe;
import net.minecraft.recipe.RecipeEntry;
import net.minecraft.registry.Registries;
import net.minecraft.server.command.CommandManager;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.text.Text;
import net.minecraft.util.Identifier;
import net.minecraft.fluid.Fluid;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public final class GtnhHelperExporterMod implements ModInitializer {
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    private static final int CONTENT_SCHEMA_VERSION = 1;

    @Override
    public void onInitialize() {
        CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) ->
            dispatcher.register(CommandManager.literal("gtnhhelper")
                .then(CommandManager.literal("export_content")
                    .executes(context -> {
                        if (!(context.getSource().getEntity() instanceof ServerPlayerEntity player)) {
                            context.getSource().sendError(Text.literal("This command can only be run by a player."));
                            return 0;
                        }

                        try {
                            Path written = exportContentSeed(player);
                            player.sendMessage(Text.literal("GTNH Helper content export written: " + written.toAbsolutePath()), false);
                            return 1;
                        } catch (IOException ex) {
                            context.getSource().sendError(Text.literal("Failed to write export: " + ex.getMessage()));
                            return 0;
                        }
                    })
                )
            )
        );
    }

    private static Path exportContentSeed(ServerPlayerEntity player) throws IOException {
        List<Identifier> itemKeys = new ArrayList<>();
        for (Item item : Registries.ITEM) {
            itemKeys.add(Registries.ITEM.getId(item));
        }
        itemKeys.sort(Comparator.comparing(Identifier::toString));

        Map<String, Integer> itemExportIds = new HashMap<>();
        JsonArray itemRows = new JsonArray();
        int nextItemId = 1;
        for (Identifier key : itemKeys) {
            String strKey = key.toString();
            itemExportIds.put(strKey, nextItemId);

            JsonObject row = new JsonObject();
            row.addProperty("id", nextItemId);
            row.addProperty("key", strKey);
            itemRows.add(row);
            nextItemId += 1;
        }

        List<Identifier> fluidKeys = new ArrayList<>();
        for (Fluid fluid : Registries.FLUID) {
            Identifier key = Registries.FLUID.getId(fluid);
            if ("minecraft:empty".equals(key.toString())) {
                continue;
            }
            fluidKeys.add(key);
        }
        fluidKeys.sort(Comparator.comparing(Identifier::toString));

        Map<String, Integer> fluidExportIds = new HashMap<>();
        JsonArray fluidRows = new JsonArray();
        int nextFluidId = 1;
        for (Identifier key : fluidKeys) {
            String strKey = key.toString();
            fluidExportIds.put(strKey, nextFluidId);

            JsonObject row = new JsonObject();
            row.addProperty("id", nextFluidId);
            row.addProperty("key", strKey);
            fluidRows.add(row);
            nextFluidId += 1;
        }

        List<RecipeEntry<?>> recipeEntries = player.getServer().getRecipeManager().values().stream()
            .sorted(Comparator.comparing(entry -> entry.id().toString()))
            .toList();

        JsonArray recipeRows = new JsonArray();
        for (RecipeEntry<?> recipeEntry : recipeEntries) {
            Recipe<?> recipe = recipeEntry.value();
            JsonObject row = new JsonObject();
            row.addProperty("id", recipeEntry.id().toString());
            Identifier recipeType = Registries.RECIPE_TYPE.getId(recipe.getType());
            row.addProperty("recipe_type", recipeType == null ? "unknown" : recipeType.toString());
            Identifier serializer = Registries.RECIPE_SERIALIZER.getId(recipe.getSerializer());
            row.addProperty("serializer", serializer == null ? "unknown" : serializer.toString());

            JsonArray inputs = new JsonArray();
            for (Ingredient ingredient : recipe.getIngredients()) {
                JsonObject ingredientRow = new JsonObject();
                JsonArray options = new JsonArray();

                for (ItemStack option : ingredient.getMatchingStacks()) {
                    if (option == null || option.isEmpty()) {
                        continue;
                    }
                    String key = Registries.ITEM.getId(option.getItem()).toString();
                    Integer exportId = itemExportIds.get(key);
                    if (exportId == null) {
                        continue;
                    }

                    JsonObject optionRow = new JsonObject();
                    optionRow.addProperty("item_id", exportId);
                    optionRow.addProperty("item_key", key);
                    options.add(optionRow);
                }

                ingredientRow.add("options", options);
                inputs.add(ingredientRow);
            }
            row.add("inputs", inputs);

            ItemStack out = recipe.getResult(player.getWorld().getRegistryManager());
            if (out != null && !out.isEmpty()) {
                String outKey = Registries.ITEM.getId(out.getItem()).toString();
                Integer outId = itemExportIds.get(outKey);
                if (outId != null) {
                    JsonObject output = new JsonObject();
                    output.addProperty("item_id", outId);
                    output.addProperty("item_key", outKey);
                    output.addProperty("count", out.getCount());
                    row.add("output", output);
                }
            }

            recipeRows.add(row);
        }

        JsonObject payload = new JsonObject();
        payload.addProperty("export_kind", "content_seed");
        payload.addProperty("schema_version", CONTENT_SCHEMA_VERSION);
        payload.addProperty("minecraft_version", player.getServer().getVersion());
        payload.addProperty("exported_at", LocalDateTime.now().toString());

        JsonObject ids = new JsonObject();
        ids.add("items", itemRows);
        ids.add("fluids", fluidRows);
        payload.add("ids", ids);
        payload.add("recipes", recipeRows);

        String safePlayer = player.getGameProfile().getName().replaceAll("[^a-zA-Z0-9._-]", "_");
        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));
        String unique = UUID.randomUUID().toString().substring(0, 8);

        Path baseDir = player.getServer().getRunDirectory().toPath()
            .resolve("config")
            .resolve("gtnh-helper")
            .resolve("content-exports");
        Files.createDirectories(baseDir);

        Path out = baseDir.resolve("content_seed_" + safePlayer + "_" + timestamp + "_" + unique + ".json");
        Files.writeString(out, GSON.toJson(payload));
        return out;
    }
}
