/**
 * 构建期把云端地址固化到 electron/cloud-config.json，供打包后的主进程读取。
 * 生产构建自动使用 https://agentht.jwdo.top，无需手动设置环境变量。
 * 仍可通过 AUTORESUME_CLOUD_URL 环境变量覆盖（用于自定义云端地址）。
 */
const fs = require('fs');
const path = require('path');

const PROD_CLOUD_URL = 'https://agentht.jwdo.top';
const url = process.env.AUTORESUME_CLOUD_URL || PROD_CLOUD_URL;
const target = path.join(__dirname, '..', 'electron', 'cloud-config.json');
fs.writeFileSync(target, JSON.stringify({ cloudUrl: url }, null, 2) + '\n', 'utf-8');
console.log(`[write-cloud-url] 云端地址已固化: ${url}`);
