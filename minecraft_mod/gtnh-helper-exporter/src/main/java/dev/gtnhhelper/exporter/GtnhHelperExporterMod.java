package dev.gtnhhelper.exporter;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import cpw.mods.fml.common.Mod;
import cpw.mods.fml.common.event.FMLServerStartingEvent;
import net.minecraft.command.CommandBase;
import net.minecraft.command.ICommandSender;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.item.crafting.CraftingManager;
import net.minecraft.item.crafting.IRecipe;
import net.minecraft.item.crafting.ShapedRecipes;
import net.minecraft.item.crafting.ShapelessRecipes;
import net.minecraft.server.MinecraftServer;
import net.minecraft.util.ChatComponentText;
import net.minecraftforge.fluids.Fluid;
import net.minecraftforge.fluids.FluidRegistry;
import net.minecraftforge.oredict.OreDictionary;
import net.minecraftforge.oredict.ShapedOreRecipe;
import net.minecraftforge.oredict.ShapelessOreRecipe;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Mod(modid = GtnhHelperExporterMod.MOD_ID, name = "GTNH Helper Content Exporter", version = "0.1.0")
public final class GtnhHelperExporterMod {
    public static final String MOD_ID = "gtnh_helper_exporter";
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    private static final int CONTENT_SCHEMA_VERSION = 1;

    @Mod.EventHandler
    public void onServerStarting(FMLServerStartingEvent event) {
        event.registerServerCommand(new ExportContentCommand());
    }

    private static final class ExportContentCommand extends CommandBase {
        @Override
        public String getCommandName() {
            return "gtnhhelper_export_content";
        }

        @Override
        public String getCommandUsage(ICommandSender sender) {
            return "/gtnhhelper_export_content";
        }

        @Override
        public int getRequiredPermissionLevel() {
            return 2;
        }

        @Override
        public void processCommand(ICommandSender sender, String[] args) {
            try {
                File out = exportContentSeed(sender.getCommandSenderName());
                sender.addChatMessage(new ChatComponentText("GTNH Helper content export written: " + out.getAbsolutePath()));
            } catch (IOException ex) {
                sender.addChatMessage(new ChatComponentText("Failed to write export: " + ex.getMessage()));
            }
        }
    }

    private static File exportContentSeed(String senderName) throws IOException {
        List<String> itemKeys = new ArrayList<String>();
        for (Object raw : Item.itemRegistry.getKeys()) {
            String key = String.valueOf(raw);
            itemKeys.add(key);
        }
        Collections.sort(itemKeys);

        Map<String, Integer> itemExportIds = new HashMap<String, Integer>();
        JsonArray itemRows = new JsonArray();
        int nextItemId = 1;
        for (String key : itemKeys) {
            itemExportIds.put(key, nextItemId);

            JsonObject row = new JsonObject();
            row.addProperty("id", nextItemId);
            row.addProperty("key", key);
            itemRows.add(row);
            nextItemId += 1;
        }

        List<String> fluidKeys = new ArrayList<String>();
        for (Fluid fluid : FluidRegistry.getRegisteredFluids().values()) {
            if (fluid == null) {
                continue;
            }
            String fluidName = fluid.getName();
            if (fluidName == null || fluidName.trim().isEmpty()) {
                continue;
            }
            fluidKeys.add(fluidName);
        }
        Collections.sort(fluidKeys);

        JsonArray fluidRows = new JsonArray();
        int nextFluidId = 1;
        for (String key : fluidKeys) {
            JsonObject row = new JsonObject();
            row.addProperty("id", nextFluidId);
            row.addProperty("key", key);
            fluidRows.add(row);
            nextFluidId += 1;
        }

        List<IRecipe> recipes = CraftingManager.getInstance().getRecipeList();
        recipes.sort(new Comparator<IRecipe>() {
            @Override
            public int compare(IRecipe a, IRecipe b) {
                String ao = recipeOutputKey(a);
                String bo = recipeOutputKey(b);
                return ao.compareTo(bo);
            }
        });

        JsonArray recipeRows = new JsonArray();
        int nextRecipeId = 1;
        for (IRecipe recipe : recipes) {
            JsonObject row = new JsonObject();
            row.addProperty("id", "recipe:" + nextRecipeId);
            row.addProperty("recipe_type", recipe.getClass().getSimpleName());

            JsonArray inputs = new JsonArray();
            appendRecipeInputs(recipe, inputs, itemExportIds);
            row.add("inputs", inputs);

            ItemStack out = recipe.getRecipeOutput();
            if (out != null) {
                String outKey = Item.itemRegistry.getNameForObject(out.getItem());
                Integer outId = itemExportIds.get(outKey);
                if (outId != null) {
                    JsonObject output = new JsonObject();
                    output.addProperty("item_id", outId);
                    output.addProperty("item_key", outKey);
                    output.addProperty("count", out.stackSize);
                    row.add("output", output);
                }
            }

            recipeRows.add(row);
            nextRecipeId += 1;
        }

        JsonObject payload = new JsonObject();
        payload.addProperty("export_kind", "content_seed");
        payload.addProperty("schema_version", CONTENT_SCHEMA_VERSION);
        payload.addProperty("minecraft_version", "1.7.10");
        payload.addProperty("exported_at", LocalDateTime.now().toString());

        JsonObject ids = new JsonObject();
        ids.add("items", itemRows);
        ids.add("fluids", fluidRows);
        payload.add("ids", ids);
        payload.add("recipes", recipeRows);

        String safeSender = senderName.replaceAll("[^a-zA-Z0-9._-]", "_");
        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));
        String unique = UUID.randomUUID().toString().substring(0, 8);

        File runDir = MinecraftServer.getServer().getFile(".");
        File baseDir = new File(new File(new File(runDir, "config"), "gtnh-helper"), "content-exports");
        if (!baseDir.exists() && !baseDir.mkdirs()) {
            throw new IOException("Could not create output directory: " + baseDir.getAbsolutePath());
        }

        File out = new File(baseDir, "content_seed_" + safeSender + "_" + timestamp + "_" + unique + ".json");
        FileWriter writer = new FileWriter(out);
        try {
            GSON.toJson(payload, writer);
        } finally {
            writer.close();
        }
        return out;
    }

    private static void appendRecipeInputs(IRecipe recipe, JsonArray inputs, Map<String, Integer> itemExportIds) {
        if (recipe instanceof ShapedRecipes) {
            ShapedRecipes shaped = (ShapedRecipes) recipe;
            for (ItemStack stack : shaped.recipeItems) {
                appendInputEntry(inputs, stack, itemExportIds);
            }
            return;
        }
        if (recipe instanceof ShapelessRecipes) {
            ShapelessRecipes shapeless = (ShapelessRecipes) recipe;
            for (Object stack : shapeless.recipeItems) {
                appendInputEntry(inputs, (ItemStack) stack, itemExportIds);
            }
            return;
        }
        if (recipe instanceof ShapedOreRecipe) {
            ShapedOreRecipe shapedOre = (ShapedOreRecipe) recipe;
            Object[] recipeInput = shapedOre.getInput();
            for (Object input : recipeInput) {
                appendOreCompatibleInput(inputs, input, itemExportIds);
            }
            return;
        }
        if (recipe instanceof ShapelessOreRecipe) {
            ShapelessOreRecipe shapelessOre = (ShapelessOreRecipe) recipe;
            @SuppressWarnings("unchecked")
            ArrayList<Object> recipeInput = shapelessOre.getInput();
            for (Object input : recipeInput) {
                appendOreCompatibleInput(inputs, input, itemExportIds);
            }
        }
    }

    private static void appendOreCompatibleInput(JsonArray inputs, Object input, Map<String, Integer> itemExportIds) {
        if (input instanceof ItemStack) {
            appendInputEntry(inputs, (ItemStack) input, itemExportIds);
            return;
        }
        if (input instanceof ArrayList) {
            @SuppressWarnings("unchecked")
            ArrayList<ItemStack> options = (ArrayList<ItemStack>) input;
            JsonObject ingredientRow = new JsonObject();
            JsonArray optionRows = new JsonArray();
            for (ItemStack stack : options) {
                appendOption(optionRows, stack, itemExportIds);
            }
            ingredientRow.add("options", optionRows);
            inputs.add(ingredientRow);
            return;
        }
        if (input instanceof String) {
            String oreName = (String) input;
            List<ItemStack> options = OreDictionary.getOres(oreName);
            JsonObject ingredientRow = new JsonObject();
            JsonArray optionRows = new JsonArray();
            for (ItemStack stack : options) {
                appendOption(optionRows, stack, itemExportIds);
            }
            ingredientRow.addProperty("ore_dict", oreName);
            ingredientRow.add("options", optionRows);
            inputs.add(ingredientRow);
        }
    }

    private static void appendInputEntry(JsonArray inputs, ItemStack stack, Map<String, Integer> itemExportIds) {
        JsonObject ingredientRow = new JsonObject();
        JsonArray options = new JsonArray();
        appendOption(options, stack, itemExportIds);
        ingredientRow.add("options", options);
        inputs.add(ingredientRow);
    }

    private static void appendOption(JsonArray optionRows, ItemStack stack, Map<String, Integer> itemExportIds) {
        if (stack == null || stack.getItem() == null) {
            return;
        }
        String key = Item.itemRegistry.getNameForObject(stack.getItem());
        Integer exportId = itemExportIds.get(key);
        if (exportId == null) {
            return;
        }
        JsonObject optionRow = new JsonObject();
        optionRow.addProperty("item_id", exportId);
        optionRow.addProperty("item_key", key);
        optionRow.addProperty("count", stack.stackSize);
        optionRows.add(optionRow);
    }

    private static String recipeOutputKey(IRecipe recipe) {
        ItemStack out = recipe.getRecipeOutput();
        if (out == null || out.getItem() == null) {
            return "~";
        }
        String key = Item.itemRegistry.getNameForObject(out.getItem());
        return key == null ? "~" : key;
    }
}
