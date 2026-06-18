const express = require('express');
const crypto = require('crypto');
const os = require('os');
const redis = require('@redis/client');
require('dotenv').config();

const app = express();
app.use(express.json({ verify: (req, _res, buf) => { req.rawBody = buf.toString('utf8'); } }));

const GITHUB_WEBHOOK_SECRET = process.env.GITHUB_WEBHOOK_SECRET;
const REDIS_URL = process.env.CELERY_BROKER_URL || 'redis://redis-broker:6379/0';

const TARGET_EXTENSIONS = ['.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs'];
const FIX_KEYWORDS = ['fix', 'bug', 'error', 'broken', 'issue', 'fail', 'crash'];

let redisClient = null;
let redisReady = false;

async function initRedis() {
    try {
        redisClient = redis.createClient({ url: REDIS_URL });
        redisClient.on('error', (err) => console.error('[REDIS] Error:', err.message));
        redisClient.on('connect', () => console.log('[REDIS] Connected'));
        redisClient.on('ready', () => {
            redisReady = true;
            console.log('[REDIS] Ready to publish tasks');
        });
        redisClient.on('end', () => {
            redisReady = false;
            console.log('[REDIS] Connection closed, reconnecting...');
            setTimeout(initRedis, 3000);
        });
        await redisClient.connect();
    } catch (err) {
        console.error('[REDIS] Init failed:', err.message);
        setTimeout(initRedis, 3000);
    }
}

function publishCeleryTask(taskName, args) {
    if (!redisReady) {
        console.warn('[QUEUE] Redis not ready');
        return false;
    }
    const taskId = crypto.randomUUID();
    const kwargs = {};
    const embeddedCallbacks = { callbacks: null, errbacks: null, chain: null, chord: null };
    const bodyPayload = Buffer.from(JSON.stringify([args, kwargs, embeddedCallbacks])).toString('base64');
    const argsrepr = JSON.stringify(args);
    const kwargsrepr = JSON.stringify(kwargs);
    const origin = `node-ingestion@${os.hostname()}`;
    const replyTo = crypto.randomUUID();

    const message = {
        body: bodyPayload,
        'content-encoding': 'utf-8',
        'content-type': 'application/json',
        headers: {
            lang: 'py',
            task: taskName,
            id: taskId,
            shadow: null,
            eta: null,
            expires: null,
            group: null,
            group_index: null,
            retries: 0,
            timelimit: [null, null],
            root_id: taskId,
            parent_id: null,
            argsrepr: argsrepr,
            kwargsrepr: kwargsrepr,
            origin: origin,
            ignore_result: false,
            replaced_task_nesting: 0,
            stamped_headers: null,
            stamps: {},
        },
        properties: {
            correlation_id: taskId,
            reply_to: replyTo,
            delivery_mode: 2,
            delivery_info: { exchange: '', routing_key: 'celery' },
            priority: 0,
            body_encoding: 'base64',
            delivery_tag: crypto.randomUUID(),
        },
    };

    const raw = JSON.stringify(message);
    redisClient.lPush('celery', raw);
    redisClient.publish('celery', raw);
    console.log(`[QUEUE] Task ${taskId} -> ${taskName}(${args.map(a => String(a).slice(0, 40)).join(', ')})`);
    return true;
}

function verifyGitHubSignature(req, res, next) {
    const signature = req.headers['x-hub-signature-256'];
    if (!signature) {
        return res.status(401).send('Missing security signature configuration.');
    }
    const hmac = crypto.createHmac('sha256', GITHUB_WEBHOOK_SECRET);
    const digest = 'sha256=' + hmac.update(req.rawBody).digest('hex');
    const checksum = Buffer.from(signature, 'utf8');
    const digestBuf = Buffer.from(digest, 'utf8');

    if (checksum.length !== digestBuf.length || !crypto.timingSafeEqual(digestBuf, checksum)) {
        return res.status(403).send('Request validation signature mismatch.');
    }
    next();
}

function containsCodeChanges(commits) {
    const start = process.hrtime.bigint();
    if (!commits || !Array.isArray(commits)) return true;
    if (commits.length === 0) return true;
    for (const commit of commits) {
        const filesChanged = [...(commit.added || []), ...(commit.modified || [])];
        for (const file of filesChanged) {
            if (TARGET_EXTENSIONS.some(ext => file.endsWith(ext))) {
                const elapsed = Number(process.hrtime.bigint() - start) / 1e6;
                console.log(`[Filtration] Evaluated ${filesChanged.length} file(s) in ${elapsed.toFixed(2)}ms — matched ${file}`);
                return true;
            }
        }
    }
    const elapsed = Number(process.hrtime.bigint() - start) / 1e6;
    console.log(`[Filtration] Evaluated ${commits.reduce((s, c) => s + (c.modified || []).length + (c.added || []).length, 0)} file(s) in ${elapsed.toFixed(2)}ms — no target source files changed.`);
    return false;
}

app.post('/webhooks/github', verifyGitHubSignature, (req, res) => {
    const payload = req.body;
    const event = req.headers['x-github-event'];

    if (event === 'pull_request' && payload.action === 'opened') {
        const commits = payload.commits || [];
        if (!containsCodeChanges(commits)) {
            return res.status(200).json({ status: "SKIPPED", message: "No operational source code changes detected." });
        }
        const taskArgs = [
            `repo_${payload.repository.id}_pr_${payload.pull_request.number}`,
            payload.installation.id.toString(),
            payload.repository.full_name,
            payload.pull_request.number,
            payload.repository.clone_url,
            null,
            null,
            null,
            payload.pull_request.base.ref,
            '',
            payload.pull_request.head.sha,
        ];
        if (publishCeleryTask('dashboard.tasks.execute_background_remediation_task', taskArgs)) {
            return res.status(202).json({ status: "QUEUED" });
        }
        return res.status(503).json({ status: "UNAVAILABLE", message: "Task queue not ready" });
    }

    if (event === 'push') {
        const ref = payload.ref;
        const defaultBranch = payload.repository.default_branch;
        const branchName = ref.replace('refs/heads/', '');

        if (branchName !== defaultBranch) {
            console.log(`[Filtration] Skipped push to ${branchName} — not default branch ${defaultBranch}.`);
            return res.status(200).json({ status: "SKIPPED", message: "Not default branch." });
        }

        const commitMessage = (payload.head_commit && payload.head_commit.message) || '';
        if (commitMessage.includes('[skip deploy]')) {
            console.log(`[Filtration] Skipped push — commit message contains [skip deploy].`);
            return res.status(200).json({ status: "SKIPPED", message: "Deployment skipped via [skip deploy]." });
        }

        const taskArgs = [
            payload.repository.owner.name || payload.repository.owner.login,
            payload.installation.id.toString(),
            payload.repository.full_name,
            payload.head_commit.id,
            branchName,
            'docker',
        ];
        if (publishCeleryTask('dashboard.tasks.execute_deployment', taskArgs)) {
            return res.status(202).json({ status: "DEPLOY_QUEUED" });
        }
        return res.status(503).json({ status: "UNAVAILABLE", message: "Task queue not ready" });
    }

    if (event === 'issues' && payload.action === 'opened') {
        const title = payload.issue.title.toLowerCase();
        const body = payload.issue.body || '';
        const hasFixIntent = FIX_KEYWORDS.some(kw => title.includes(kw) || body.toLowerCase().includes(kw));
        if (!hasFixIntent) {
            console.log(`[Filtration] Skipped issue #${payload.issue.number} — no fix-related keywords detected.`);
            return res.status(200).json({ status: "SKIPPED", message: "No fix-related keywords in issue." });
        }
        const projectId = `repo_${payload.repository.id}_issue_${payload.issue.number}`;
        const bugDescription = `${payload.issue.title}\n\n${body}`;
        const taskArgs = [
            projectId,
            payload.installation.id.toString(),
            payload.repository.full_name,
            0,
            payload.repository.clone_url,
            bugDescription,
            null,
            null,
            'main',
            '',
            '',
        ];
        if (publishCeleryTask('dashboard.tasks.execute_background_remediation_task', taskArgs)) {
            return res.status(202).json({ status: "QUEUED_FROM_ISSUE" });
        }
        return res.status(503).json({ status: "UNAVAILABLE", message: "Task queue not ready" });
    }

    return res.status(200).json({ status: "IGNORED", event: event || "unknown", action: payload.action || "unknown" });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, async () => {
    console.log(`Ingestion Gateway operating smoothly on port ${PORT}`);
    await initRedis();
});
