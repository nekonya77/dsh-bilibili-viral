#!/usr/bin/env node
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const fail = (message) => {
  console.error(`✗ ${message}`);
  process.exit(1);
};
const read = (path) => readFileSync(join(root, path), 'utf-8');

const pkg = JSON.parse(read('package.json'));
if (pkg.name !== 'dsh-bilibili-viral') fail('package.json name must be dsh-bilibili-viral');
if (!pkg.dsh || !pkg.dsh.bundle || pkg.dsh.bundle.patch !== './cordis.patch.yml') {
  fail('package.json must declare dsh.bundle.patch = ./cordis.patch.yml');
}
if (!existsSync(join(root, 'cordis.patch.yml'))) fail('cordis.patch.yml is missing');

const patch = read('cordis.patch.yml');
if (!patch.includes('bilibili-viral-skill') || !patch.includes('dsh-bilibili-viral')) {
  fail('cordis.patch.yml must insert bilibili-viral-skill / dsh-bilibili-viral');
}

const skillPath = 'skills/bilibili-viral/SKILL.md';
if (!existsSync(join(root, skillPath))) fail(`${skillPath} is missing`);
const skill = read(skillPath);
const fm = skill.match(/^---\r?\n([\s\S]*?)\r?\n---/);
if (!fm) fail('SKILL.md frontmatter is missing');
const name = fm[1].match(/^name:\s*(.+)$/m)?.[1]?.trim();
const description = fm[1].match(/^description:\s*(.+)$/m)?.[1]?.trim();
if (name !== 'bilibili-viral') fail(`SKILL.md name must be bilibili-viral, got ${name}`);
if (!description || description.length > 500) fail('SKILL.md description must be 1-500 characters');

for (const file of ['lib/index.js', 'bili_viral/__main__.py', 'requirements.txt', 'README.md', 'LICENSE']) {
  if (!existsSync(join(root, file))) fail(`${file} is missing`);
}

console.log('✓ bundle manifest, patch, skill frontmatter, and required files are valid');
