-- Allow 'vwapfade' as a bot_config.style value.
-- The original CHECK constraint only permitted 'scalping'/'swing', so starting
-- the bot with style='vwapfade' failed with:
--   new row for relation "bot_config" violates check constraint "bot_config_style_check"
ALTER TABLE bot_config DROP CONSTRAINT IF EXISTS bot_config_style_check;
ALTER TABLE bot_config ADD CONSTRAINT bot_config_style_check
  CHECK (style IN ('scalping', 'swing', 'vwapfade'));
