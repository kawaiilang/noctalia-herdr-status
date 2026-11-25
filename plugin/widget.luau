local COLORS = {
    blocked = "error",
    working = "primary",
    done = "tertiary",
    idle = "on_surface_variant",
    shells = "on_surface_variant",
    empty = "on_surface_variant",
    offline = "on_surface_variant",
    unknown = "on_surface_variant",
}

local GLYPHS = {
    blocked = "alert-triangle",
    working = "terminal-2",
    done = "circle-check",
    idle = "terminal-2",
    shells = "terminal-2",
    empty = "terminal-2",
    offline = "terminal-2",
    unknown = "terminal-2",
}

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

local function barText(state, counts)
    if state == "blocked" then
        return noctalia.tr("bar_blocked", { count = tostring(counts.blocked or 0) })
    elseif state == "working" then
        return noctalia.tr("bar_working", { count = tostring(counts.working or 0) })
    elseif state == "done" then
        return noctalia.tr("bar_done", { count = tostring(counts.done or 0) })
    elseif state == "idle" then
        return noctalia.tr("bar_idle", { count = tostring(counts.idle or 0) })
    elseif state == "unknown" and (counts.unknown or 0) > 0 then
        return noctalia.tr("bar_agents_unknown", { count = tostring(counts.unknown) })
    elseif state == "shells" then
        return noctalia.tr("bar_shells", { count = tostring(counts.shells or 0) })
    elseif state == "empty" then
        return noctalia.tr("bar_empty")
    elseif state == "offline" then
        return noctalia.tr("bar_offline")
    end
    return noctalia.tr("bar_unknown")
end

local function agentSummary(counts)
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
    if #parts == 0 then
        return "0"
    end
    return table.concat(parts, " · ")
end

local function render(value)
    local snapshot = type(value) == "table" and value or fallbackSnapshot()
    local state = COLORS[snapshot.state] and snapshot.state or "unknown"
    local counts = type(snapshot.counts) == "table" and snapshot.counts or fallbackSnapshot().counts
    local color = COLORS[state]
    local glyph = GLYPHS[state]

    barWidget.setGlyph(glyph)
    barWidget.setText(barText(state, counts))
    barWidget.setColor(color)
    barWidget.setGlyphColor(color)
    barWidget.setTooltip({
        { noctalia.tr("tooltip_status"), noctalia.tr(if state == "unknown" and snapshot.running then "detail_agents_unknown" else "detail_" .. state) },
        { noctalia.tr("tooltip_agents"), agentSummary(counts) },
        { noctalia.tr("tooltip_shells"), tostring(counts.shells or 0) },
        { noctalia.tr("tooltip_action"), noctalia.tr("tooltip_click_hint") },
    })
end

noctalia.state.watch("status", render)
render(noctalia.state.get("status"))

function onClick()
    noctalia.state.set("refresh", (noctalia.state.get("refresh") or 0) + 1)
    noctalia.togglePanel("kawaiilang/herdr-status:panel")
end
