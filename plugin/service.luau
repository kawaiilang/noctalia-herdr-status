local pending = false
local refreshAfterPoll = false
local stopped = false
local lastActionSeq = nil

local VALID_STATES = {
    offline = true,
    blocked = true,
    working = true,
    done = true,
    idle = true,
    shells = true,
    empty = true,
    unknown = true,
}

local VALID_ITEM_STATUSES = {
    blocked = true,
    working = true,
    done = true,
    idle = true,
    unknown = true,
    shell = true,
}

local COUNT_KEYS = {
    "blocked",
    "working",
    "done",
    "idle",
    "unknown",
    "agents",
    "shells",
    "total",
}

local function emptyCounts()
    return {
        blocked = 0,
        working = 0,
        done = 0,
        idle = 0,
        unknown = 0,
        agents = 0,
        shells = 0,
        total = 0,
    }
end

local function unknownSnapshot()
    return {
        state = "unknown",
        running = false,
        counts = emptyCounts(),
        agents = {},
        shells = {},
    }
end

local function publishUnknown()
    noctalia.state.set("status", unknownSnapshot())
end

local function isValidEntry(entry)
    if type(entry) ~= "table" then
        return false
    end
    return type(entry.pane_id) == "string"
        and entry.pane_id ~= ""
        and type(entry.name) == "string"
        and type(entry.agent) == "string"
        and VALID_ITEM_STATUSES[entry.status] == true
        and type(entry.dir) == "string"
        and type(entry.workspace) == "string"
        and type(entry.tab) == "string"
        and type(entry.focused) == "boolean"
end

local function isValidEntryList(list)
    if type(list) ~= "table" then
        return false
    end
    for index, entry in ipairs(list) do
        if type(index) ~= "number" or not isValidEntry(entry) then
            return false
        end
    end
    return true
end

local function isValidSnapshot(value)
    if type(value) ~= "table" then
        return false
    end
    if not VALID_STATES[value.state] then
        return false
    end
    if type(value.running) ~= "boolean" then
        return false
    end
    if type(value.counts) ~= "table" then
        return false
    end
    for _, key in ipairs(COUNT_KEYS) do
        if type(value.counts[key]) ~= "number" then
            return false
        end
    end
    return isValidEntryList(value.agents) and isValidEntryList(value.shells)
end

local function refresh()
    if pending or stopped then
        return
    end
    pending = true
    local launched = noctalia.runAsync({ "@helperCommand@", "status" }, function(result)
        if stopped then
            return
        end
        pending = false
        if refreshAfterPoll then
            refreshAfterPoll = false
            refresh()
            return
        end
        if result.exitCode ~= 0 or result.timedOut or result.stdoutTruncated then
            publishUnknown()
            return
        end
        local ok, value = pcall(noctalia.json.decode, result.stdout)
        if not ok or not isValidSnapshot(value) then
            publishUnknown()
            return
        end
        noctalia.state.set("status", value)
    end, 2500)
    if not launched then
        pending = false
        publishUnknown()
    end
end

local function handleAction(action)
    if stopped or type(action) ~= "table" then
        return
    end
    if action.seq ~= nil and action.seq == lastActionSeq then
        return
    end
    lastActionSeq = action.seq

    if action.kind ~= "focus" or type(action.pane_id) ~= "string" or action.pane_id == "" then
        return
    end

    local function finish(ok)
        if stopped then
            return
        end
        noctalia.state.set("actionResult", { seq = action.seq, kind = action.kind, ok = ok })
        if pending then
            refreshAfterPoll = true
        else
            refresh()
        end
    end
    local launched = noctalia.runAsync({ "@helperCommand@", "focus", action.pane_id }, function(result)
        finish(result.exitCode == 0 and not result.timedOut)
    end, 4000)
    if not launched then
        finish(false)
    end
end

noctalia.setUpdateInterval(3000)
noctalia.state.watch("refresh", refresh)
noctalia.state.watch("action", handleAction)
publishUnknown()
refresh()

function update()
    refresh()
end

function onExit(_signal, _reason)
    stopped = true
end
