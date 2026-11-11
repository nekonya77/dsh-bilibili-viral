/**
 * dsh-bilibili-viral bundle entry.
 *
 * Registers the bundled Bilibili viral-content radar skill with ctx.skills.
 * The skill body lives in skills/bilibili-viral/SKILL.md; relative references
 * resolve against that directory through resourceBase.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const name = 'bilibili-viral-skill';
export const inject = ['skills'];

const SKILL_DIR = new URL('../skills/bilibili-viral/', import.meta.url);
const SKILL_FILE = new URL('SKILL.md', SKILL_DIR);

function parseFrontmatter(text) {
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (!match) return null;
  const fm = match[1];
  const get = (key) => {
    const line = fm.match(new RegExp('^' + key + ':\\s*(.+)$', 'm'));
    if (!line) return undefined;
    let value = line[1].trim();
    const quoted = (value.startsWith('"') && value.endsWith('"'))
      || (value.startsWith("'") && value.endsWith("'"));
    if (quoted) value = value.slice(1, -1);
    return value;
  };
  return {
    name: get('name'),
    description: get('description'),
    whenToUse: get('whenToUse'),
  };
}

export function apply(ctx) {
  let raw;
  try {
    raw = readFileSync(SKILL_FILE, 'utf-8');
  } catch (error) {
    ctx.logger.error('dsh-bilibili-viral: cannot read SKILL.md: %s', error.message);
    return;
  }

  const meta = parseFrontmatter(raw);
  if (!meta || !meta.name || !meta.description) {
    ctx.logger.error(
      'dsh-bilibili-viral: SKILL.md frontmatter missing name/description; skill not registered',
    );
    return;
  }

  const content = raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '').trimStart();
  const skill = {
    name: meta.name,
    description: meta.description,
    ...(meta.whenToUse ? { whenToUse: meta.whenToUse } : {}),
    content,
    source: 'runtime',
    resourceBase: {
      kind: 'directory',
      path: fileURLToPath(SKILL_DIR),
    },
  };

  ctx.logger.info('dsh-bilibili-viral: registered skill "%s"', skill.name);
  ctx.effect(() => ctx.skills.register(skill));
}
