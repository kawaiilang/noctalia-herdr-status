local values = {}
local watchers = {}
local calls = {}
local launched = true
local decoded = nil
local decodeFails = false
local interval = nil
local displayed = {}
local toggledPanels = {}
local panelClosedCount = 0
local settings = {}

local noctalia = {
    state = {
        set = function(key, value)
            values[key] = value
            if watchers[key] then
                watchers[key](value)
            end
        end,
        get = function(key)
            return values[key]
        end,
        watch = function(key, fn)
            watchers[key] = fn
        end,
    },
    setUpdateInterval = function(ms)
        interval = ms
    end,
    runAsync = function(argv, callback, timeout)
        assert(type(argv) == "table" and #argv >= 2, "must pass direct argv")
        table.insert(calls, { argv = argv, callback = callback, timeout = timeout })
        return launched
    end,
    json = {
        decode = function(_text)
            if decodeFails then
                error("invalid JSON")
            end
            return decoded
        end,
    },
    tr = function(key, subst)
        if type(subst) == "table" and subst.count ~= nil then
            return key .. ":" .. tostring(subst.count)
        end
        return key
    end,
    togglePanel = function(id)
        table.insert(toggledPanels, id)
    end,
    getSetting = function(key)
        return settings[key]
    end,
}

local barWidget = {
    setGlyph = function(value)
        displayed.glyph = value
    end,
    setText = function(value)
        displayed.text = value
    end,
    setColor = function(value)
        displayed.color = value
    end,
    setGlyphColor = function(value)
        displayed.glyphColor = value
    end,
    setTooltip = function(value)
        displayed.tooltip = value
    end,
}

local ui = {}
for _, kind in { "column", "row", "glyph", "label", "button", "separator", "scroll" } do
    ui[kind] = function(props, children)
        return { kind = kind, props = props, children = children or {} }
    end
end

local panel = {
    render = function(tree)
        displayed.tree = tree
    end,
    close = function()
        panelClosedCount = panelClosedCount + 1
    end,
}
