-- dump_decals.lua — export Motor Town's vehicle decal render targets to PNG.
--
-- Why: the decal render target is the game's own answer to how a layer maps onto the
-- body. MTDecalBaker draws the target mesh into DecalRT through the vehicle's decal UV,
-- so the PNG it produces is already in that UV space. Compare it with the saved layer
-- list (Position/Rotation/DecalScale) and the mapping can be solved instead of guessed.
--
-- Install: drop this file in <MotorTown>/Binaries/Win64/Mods/DecalDump/Scripts/main.lua
--          together with an enabled.txt in the same folder.
-- Use:     stand in the garage with a decaled vehicle shown, press F8.
-- Output:  <MotorTown>/Saved/DecalDump/*.png  (plus decal_dump.json with object names)
--
-- Safe: read-only. It only enumerates objects and exports render targets; it hooks
-- nothing and changes no state.

local UEHelpers = require("UEHelpers")
local OUT_DIR = "DecalDump"
local dumped = 0

local function sanitize(s)
    return (s:gsub("[^%w_%-]", "_"))
end

local function find_world_context()
    local pc = UEHelpers.GetPlayerController()
    if pc and pc:IsValid() then return pc end
    local pawn = UEHelpers.GetPlayerPawn()
    if pawn and pawn:IsValid() then return pawn end
    return nil
end

local function dump_targets()
    local ctx = find_world_context()
    if not ctx then
        print("[DecalDump] no player controller or pawn yet -- load into the world first\n")
        return
    end

    local rts = FindAllOf("TextureRenderTarget2D") or {}
    local names = {}
    local count = 0

    for _, rt in pairs(rts) do
        if rt and rt:IsValid() then
            local full = rt:GetFullName()
            -- vehicle decal targets are named after the baker/target mesh; keep the
            -- filter loose because the exact naming differs per vehicle
            if full and (full:find("Decal") or full:find("decal")) then
                local file = sanitize(full) .. ".png"
                -- UE4SS resolves this either as a static call or as a library method
                -- depending on the build; try both before giving up
                local ok = pcall(function()
                    KismetRenderingLibrary.ExportRenderTarget(ctx, rt, OUT_DIR, file)
                end)
                if not ok then
                    ok = pcall(function()
                        KismetRenderingLibrary:ExportRenderTarget(ctx, rt, OUT_DIR, file)
                    end)
                end
                names[#names + 1] = { name = full, file = file, exported = ok }
                if ok then count = count + 1 end
            end
        end
    end

    local f = io.open("DecalDump/decal_dump.json", "w")
    if f then
        f:write(string.format('{"count":%d,"targets":[', count))
        for i, t in ipairs(names) do
            f:write(string.format('%s{"name":"%s","file":"%s"}',
                i > 1 and "," or "", t.name, t.file))
        end
        f:write("]}\n")
        f:close()
    end

    dumped = dumped + count
    print(string.format("[DecalDump] exported %d decal render target(s), %d total this session\n", count, dumped))
end

RegisterKeyBind(Key.F8, function() dump_targets() end)
print("[DecalDump] ready -- press F8 in the garage with a decaled vehicle visible\n")
