--!nonstrict
local STATUS_COLORS = {
    blocked = "error",
    working = "primary",
    done = "tertiary",
    idle = "secondary",
    shell = "on_surface_variant",
}

local WORKSPACE_HEADER_COLORS = {
    blocked = "error",
    working = "primary",
    done = "tertiary",
    idle = "secondary",
    unknown = "secondary",
    shell = "on_surface_variant",
}

local STATUS_PRIORITY = {
    blocked = 0,
    working = 1,
    done = 2,
    idle = 3,
    unknown = 4,
    shell = 5,
}

local STATUS_GLYPHS = {
    blocked = "alert-triangle",
    working = "player-play",
    done = "circle-check",
    idle = "moon",
    shell = "terminal-2",
}

local closeButton = true
local pendingSeq = nil
local errorKey = nil
local render

local function fallbackSnapshot()
    return {
        state = "unknown",
        running = false,
        counts = {
            blocked = 0,
            working = 0,
            done = 0,
            idle = 0,
            unknown = 0,
            agents = 0,
            shells = 0,
            total = 0,
        },
        agents = {},
        shells = {},
    }
end

local snapshot = fallbackSnapshot()

local function sendFocusAction(paneId)
    if pendingSeq ~= nil then
        return
    end
    local previous = noctalia.state.get("action")
    pendingSeq = (if type(previous) == "table" then previous.seq or 0 else 0) + 1
    errorKey = nil
    render()
    noctalia.state.set("action", {
        seq = pendingSeq,
        kind = "focus",
        pane_id = paneId,
    })
end

local function entrySubtitle(entry, title)
    local parts = {}
    local workspaceLower = type(entry.workspace) == "string" and string.lower(entry.workspace) or ""
    local titleLower = string.lower(title)
    if type(entry.tab) == "string" and entry.tab ~= "" and string.lower(entry.tab) ~= titleLower then
        table.insert(parts, entry.tab)
    end
    if
        type(entry.dir) == "string"
        and entry.dir ~= ""
        and string.lower(entry.dir) ~= workspaceLower
        and string.lower(entry.dir) ~= titleLower
    then
        table.insert(parts, entry.dir)
    end
    table.insert(parts, entry.pane_id)
    return table.concat(parts, " · ")
end

local function entryRow(entry)
    local title = entry.name ~= "" and entry.name or entry.pane_id
    local label = noctalia.tr("item_" .. entry.status)
    local subtitle = entrySubtitle(entry, title)
    local variant = entry.status == "blocked" and "outline" or "ghost"
    local color = STATUS_COLORS[entry.status] or "on_surface_variant"
    local text = title .. " (" .. label .. ") · " .. subtitle

    return ui.row({ gap = 8, align = "center" }, {
        ui.glyph({
            name = STATUS_GLYPHS[entry.status] or "terminal-2",
            size = 16,
            color = color,
        }),
        ui.button({
            key = "entry-" .. entry.pane_id,
            text = text,
            enabled = pendingSeq == nil,
            selected = entry.focused == true,
            contentAlign = "start",
            variant = variant,
            flexGrow = 1,
            tooltip = noctalia.tr("panel_focus_hint"),
            onClick = function()
                sendFocusAction(entry.pane_id)
            end,
        }),
    })
end

local function summaryText(counts)
    local parts = {}
    if (counts.blocked or 0) > 0 then
        table.insert(parts, noctalia.tr("count_blocked", { count = tostring(counts.blocked) }))
    end
    if (counts.working or 0) > 0 then
        table.insert(parts, noctalia.tr("count_working", { count = tostring(counts.working) }))
    end
    if (counts.done or 0) > 0 then
        table.insert(parts, noctalia.tr("count_done", { count = tostring(counts.done) }))
    end
    if (counts.idle or 0) > 0 then
        table.insert(parts, noctalia.tr("count_idle", { count = tostring(counts.idle) }))
    end
    if (counts.unknown or 0) > 0 then
        table.insert(parts, noctalia.tr("count_unknown", { count = tostring(counts.unknown) }))
    end
    if (counts.shells or 0) > 0 then
        table.insert(parts, noctalia.tr("count_shells", { count = tostring(counts.shells) }))
    end
    if #parts == 0 then
        return noctalia.tr("panel_empty")
    end
    return table.concat(parts, " · ")
end

local function groupByWorkspace(entries)
    local byName = {}
    local groups = {}

    for _, entry in ipairs(entries) do
        local name = type(entry.workspace) == "string" and entry.workspace or ""
        local group = byName[name]
        if group == nil then
            group = {
                name = name,
                entries = {},
                bestStatus = entry.status or "unknown",
                bestPriority = STATUS_PRIORITY[entry.status] or 99,
                counts = {
                    blocked = 0,
                    working = 0,
                    done = 0,
                    idle = 0,
                    unknown = 0,
                    shells = 0,
                },
            }
            byName[name] = group
            table.insert(groups, group)
        end

        table.insert(group.entries, entry)
        local priority = STATUS_PRIORITY[entry.status] or 99
        if priority < group.bestPriority then
            group.bestPriority = priority
            group.bestStatus = entry.status
        end
        if entry.status == "shell" then
            group.counts.shells += 1
        elseif group.counts[entry.status] ~= nil then
            group.counts[entry.status] += 1
        else
            group.counts.unknown += 1
        end
    end

    table.sort(groups, function(a, b)
        if a.bestPriority ~= b.bestPriority then
            return a.bestPriority < b.bestPriority
        end
        local aNamed = a.name ~= ""
        local bNamed = b.name ~= ""
        if aNamed ~= bNamed then
            return aNamed
        end
        return string.lower(a.name) < string.lower(b.name)
    end)

    return groups
end

local function workspaceCard(group, isShellSection)
    local workspaceLabel = group.name ~= "" and group.name or noctalia.tr("panel_workspace_unassigned")
    local headerColor = if isShellSection
        then "on_surface_variant"
        else WORKSPACE_HEADER_COLORS[group.bestStatus] or "secondary"
    local headerGlyph = if isShellSection then "terminal-2" else "layout-board"
    local countColor = group.bestStatus == "blocked" and "error" or "on_surface_variant"

    local cardChildren = {
        ui.row({ gap = 6, align = "center" }, {
            ui.glyph({ name = headerGlyph, size = 14, color = headerColor }),
            ui.label({
                text = workspaceLabel,
                fontSize = 13,
                fontWeight = "bold",
                color = headerColor,
                flexGrow = 1,
                maxLines = 1,
            }),
            ui.label({
                text = summaryText(group.counts),
                fontSize = 11,
                color = countColor,
            }),
        }),
    }

    for _, entry in ipairs(group.entries) do
        table.insert(cardChildren, entryRow(entry))
    end

    return ui.column({ gap = 4, padding = 8, radius = 8, fill = "surface_container/0.35" }, cardChildren)
end

local function renderOffline(state)
    local detailKey = state == "offline" and "detail_offline" or "detail_unknown"
    return ui.column({ gap = 10, padding = 12, radius = 8, fill = "surface_container/0.35" }, {
        ui.row({ gap = 8, align = "center" }, {
            ui.glyph({ name = "terminal-2", size = 20, color = "on_surface_variant" }),
            ui.label({
                text = noctalia.tr(detailKey),
                color = "on_surface_variant",
                fontSize = 12,
                flexGrow = 1,
            }),
        }),
    })
end

render = function()
    local state = snapshot.state or "unknown"
    local counts = type(snapshot.counts) == "table" and snapshot.counts or fallbackSnapshot().counts
    local headerChildren = {
        ui.glyph({ name = "terminal-2", size = 20, color = "primary" }),
        ui.label({ text = noctalia.tr("panel_title"), fontSize = 16, fontWeight = "bold", flexGrow = 1 }),
        ui.button({
            glyph = "refresh",
            variant = "ghost",
            tooltip = noctalia.tr("panel_refresh"),
            onClick = "onRefreshClicked",
        }),
    }
    if closeButton then
        table.insert(headerChildren, ui.button({
            glyph = "close",
            variant = "ghost",
            onClick = "onCloseClicked",
        }))
    end

    local children = { ui.row({ align = "center", gap = 6 }, headerChildren) }
    if errorKey then
        table.insert(children, ui.label({ text = noctalia.tr(errorKey), color = "error" }))
    end

    if snapshot.running ~= true then
        table.insert(children, renderOffline(state))
        panel.render(ui.column({ flexGrow = 1, gap = 10, padding = 12 }, children))
        return
    end

    local rows = {}
    local agents = type(snapshot.agents) == "table" and snapshot.agents or {}
    local shells = type(snapshot.shells) == "table" and snapshot.shells or {}

    if #agents > 0 then
        table.insert(rows, ui.label({
            text = noctalia.tr("panel_agents_section", { count = tostring(#agents) }),
            fontSize = 12,
            fontWeight = "bold",
            color = "on_surface_variant",
        }))
        for _, group in ipairs(groupByWorkspace(agents)) do
            table.insert(rows, workspaceCard(group, false))
        end
    end

    if #shells > 0 then
        if #agents > 0 then
            table.insert(rows, ui.separator({}))
        end
        table.insert(rows, ui.label({
            text = noctalia.tr("panel_shells_section", { count = tostring(#shells) }),
            fontSize = 12,
            fontWeight = "bold",
            color = "on_surface_variant",
        }))
        for _, group in ipairs(groupByWorkspace(shells)) do
            table.insert(rows, workspaceCard(group, true))
        end
    end

    if #rows == 0 then
        table.insert(rows, ui.label({
            text = noctalia.tr("panel_empty"),
            color = "on_surface_variant",
            fontSize = 12,
        }))
    end

    local summaryCard = ui.row({ gap = 8, align = "center", padding = 8, radius = 8, fill = "surface_container/0.35" }, {
        ui.label({
            text = summaryText(counts),
            fontSize = 12,
            color = state == "blocked" and "error" or "on_surface",
            flexGrow = 1,
        }),
    })

    table.insert(children, summaryCard)
    table.insert(children, ui.scroll({ flexGrow = 1, gap = 8 }, rows))
    panel.render(ui.column({ flexGrow = 1, gap = 8, padding = 12 }, children))
end

function onRefreshClicked()
    noctalia.state.set("refresh", (noctalia.state.get("refresh") or 0) + 1)
end

function onCloseClicked()
    panel.close()
end

function onOpen(_context)
    pendingSeq = nil
    errorKey = nil
    closeButton = noctalia.getSetting("shell.show_close_buttons") ~= false
    snapshot = noctalia.state.get("status") or fallbackSnapshot()
    noctalia.state.set("refresh", (noctalia.state.get("refresh") or 0) + 1)
    render()
end

function onClose()
    pendingSeq = nil
end

noctalia.state.watch("actionResult", function(result)
    if pendingSeq == nil or type(result) ~= "table" or result.seq ~= pendingSeq then
        return
    end
    pendingSeq = nil
    if result.ok then
        panel.close()
    else
        errorKey = "panel_focus_failed"
        render()
    end
end)

noctalia.state.watch("status", function(value)
    if type(value) == "table" then
        snapshot = value
        render()
    end
end)
