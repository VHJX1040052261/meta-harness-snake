// game.js
(() => {
  /* ── 核心数据结构 ── */
  const COLS = 20;
  const ROWS = 20;
  const CELL = 24;
  const GAP = 1;
  const TICK_INTERVAL = 130; // ms

  const Dir = Object.freeze({
    UP:    { x:  0, y: -1 },
    DOWN:  { x:  0, y:  1 },
    LEFT:  { x: -1, y:  0 },
    RIGHT: { x:  1, y:  0 },
  });

  const OPPOSITE = {
    [key(Dir.UP)]:    key(Dir.DOWN),
    [key(Dir.DOWN)]:  key(Dir.UP),
    [key(Dir.LEFT)]:  key(Dir.RIGHT),
    [key(Dir.RIGHT)]: key(Dir.LEFT),
  };

  function key(d) { return `${d.x},${d.y}`; }

  /* ── DOM 引用 ── */
  const canvas = document.getElementById('gameCanvas');
  const ctx = canvas.getContext('2d');
  canvas.width = COLS * CELL;
  canvas.height = ROWS * CELL;

  const scoreEl = document.getElementById('score');
  const highScoreEl = document.getElementById('highScore');
  const overlay = document.getElementById('overlay');
  const overlayText = document.getElementById('overlayText');
  const overlayBtn = document.getElementById('overlayBtn');

  /* ── 状态 ── */
  let snake = [];
  let food = null;
  let direction = Dir.RIGHT;
  let nextDirection = Dir.RIGHT;
  let score = 0;
  let highScore = 0;
  let ticker = null;
  let running = false;
  let gameOver = false;
  let paused = false;

  /* ── 持久化最高分 ── */
  try {
    const saved = localStorage.getItem('snake_high_score');
    if (saved !== null) highScore = parseInt(saved, 10) || 0;
  } catch (_) { /* 无 localStorage */ }
  highScoreEl.textContent = highScore;

  function saveHighScore() {
    if (score > highScore) {
      highScore = score;
      highScoreEl.textContent = highScore;
      try { localStorage.setItem('snake_high_score', highScore); } catch (_) {}
    }
  }

  /* ── 食物生成 ── */
  function randomCell() {
    return {
      x: Math.floor(Math.random() * COLS),
      y: Math.floor(Math.random() * ROWS),
    };
  }

  function occupiedSet() {
    const s = new Set();
    for (const seg of snake) s.add(`${seg.x},${seg.y}`);
    return s;
  }

  function spawnFood() {
    const occ = occupiedSet();
    let candidate;
    let tries = 0;
    do {
      candidate = randomCell();
      tries++;
      if (tries > COLS * ROWS * 2) break;
    } while (occ.has(`${candidate.x},${candidate.y}`));
    food = candidate;
  }

  /* ── 初始化 / 重置 ── */
  function initGame() {
    const startX = Math.floor(COLS / 2);
    const startY = Math.floor(ROWS / 2);
    snake = [
      { x: startX,     y: startY },
      { x: startX - 1, y: startY },
      { x: startX - 2, y: startY },
    ];
    direction = Dir.RIGHT;
    nextDirection = Dir.RIGHT;
    score = 0;
    gameOver = false;
    paused = false;
    scoreEl.textContent = '0';
    spawnFood();
    draw();
    showOverlay(false);
  }

  /* ── 移动逻辑 ── */
  function step() {
    if (!running || gameOver || paused) return;

    direction = nextDirection;

    const head = snake[0];
    const newHead = {
      x: head.x + direction.x,
      y: head.y + direction.y,
    };

    // 撞墙检测
    if (newHead.x < 0 || newHead.x >= COLS || newHead.y < 0 || newHead.y >= ROWS) {
      return endGame();
    }

    // 撞自身检测（排除尾部，因为尾部即将移除——除非吃了食物）
    const willEat = food && newHead.x === food.x && newHead.y === food.y;
    const bodyCheck = willEat ? snake : snake.slice(0, -1);
    for (const seg of bodyCheck) {
      if (seg.x === newHead.x && seg.y === newHead.y) {
        return endGame();
      }
    }

    // 前进
    snake.unshift(newHead);

    if (willEat) {
      score++;
      scoreEl.textContent = score;
      spawnFood();
    } else {
      snake.pop();
    }

    draw();
  }

  /* ── 游戏结束 ── */
  function endGame() {
    gameOver = true;
    stopLoop();
    saveHighScore();
    draw();
    showOverlay(true, '游戏结束', '重新开始');
  }

  /* ── 渲染 ── */
  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // 绘制网格线
    ctx.strokeStyle = '#181835';
    ctx.lineWidth = 0.5;
    for (let r = 0; r <= ROWS; r++) {
      ctx.beginPath();
      ctx.moveTo(0, r * CELL);
      ctx.lineTo(COLS * CELL, r * CELL);
      ctx.stroke();
    }
    for (let c = 0; c <= COLS; c++) {
      ctx.beginPath();
      ctx.moveTo(c * CELL, 0);
      ctx.lineTo(c * CELL, ROWS * CELL);
      ctx.stroke();
    }

    // 绘制食物
    if (food) {
      const fx = food.x * CELL + CELL / 2;
      const fy = food.y * CELL + CELL / 2;
      const r = CELL / 2 - 3;
      ctx.fillStyle = '#ff5252';
      ctx.shadowColor = '#ff5252';
      ctx.shadowBlur = 8;
      ctx.beginPath();
      ctx.arc(fx, fy, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      // 高光
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.beginPath();
      ctx.arc(fx - r * 0.3, fy - r * 0.3, r * 0.35, 0, Math.PI * 2);
      ctx.fill();
    }

    // 绘制蛇身
    for (let i = snake.length - 1; i >= 0; i--) {
      const seg = snake[i];
      const sx = seg.x * CELL + GAP;
      const sy = seg.y * CELL + GAP;
      const size = CELL - GAP * 2;

      const t = snake.length > 1 ? i / (snake.length - 1) : 0;
      const r = Math.floor(0  + t * 0);
      const g = Math.floor(180 + t * 50);
      const b = Math.floor(80  + t * 100);

      ctx.fillStyle = i === 0
        ? '#00e676'
        : `rgb(${r},${g},${b})`;
      ctx.shadowColor = i === 0 ? '#00e676' : 'transparent';
      ctx.shadowBlur = i === 0 ? 6 : 0;

      const radius = 5;
      ctx.beginPath();
      ctx.moveTo(sx + radius, sy);
      ctx.lineTo(sx + size - radius, sy);
      ctx.quadraticCurveTo(sx + size, sy, sx + size, sy + radius);
      ctx.lineTo(sx + size, sy + size - radius);
      ctx.quadraticCurveTo(sx + size, sy + size, sx + size - radius, sy + size);
      ctx.lineTo(sx + radius, sy + size);
      ctx.quadraticCurveTo(sx, sy + size, sx, sy + size - radius);
      ctx.lineTo(sx, sy + radius);
      ctx.quadraticCurveTo(sx, sy, sx + radius, sy);
      ctx.closePath();
      ctx.fill();
      ctx.shadowBlur = 0;

      // 蛇头眼睛
      if (i === 0) {
        ctx.fillStyle = '#0a0a1a';
        const cx = seg.x * CELL + CELL / 2;
        const cy = seg.y * CELL + CELL / 2;
        const eyeR = 3;
        let ex1, ey1, ex2, ey2;
        if (direction.x === 1)      { ex1 = cx + 4; ey1 = cy - 4; ex2 = cx + 4; ey2 = cy + 4; }
        else if (direction.x === -1) { ex1 = cx - 4; ey1 = cy - 4; ex2 = cx - 4; ey2 = cy + 4; }
        else if (direction.y === -1) { ex1 = cx - 4; ey1 = cy - 4; ex2 = cx + 4; ey2 = cy - 4; }
        else                        { ex1 = cx - 4; ey1 = cy + 4; ex2 = cx + 4; ey2 = cy + 4; }
        ctx.beginPath();
        ctx.arc(ex1, ey1, eyeR, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.arc(ex2, ey2, eyeR, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  /* ── Overlay 控制 ── */
  function showOverlay(visible, text, btnText) {
    if (visible) {
      overlay.classList.remove('hidden');
      overlayText.textContent = text || '';
      overlayBtn.textContent = btnText || '开始';
    } else {
      overlay.classList.add('hidden');
    }
  }

  /* ── 主循环 ── */
  function startLoop() {
    stopLoop();
    ticker = setInterval(step, TICK_INTERVAL);
  }

  function stopLoop() {
    if (ticker !== null) {
      clearInterval(ticker);
      ticker = null;
    }
  }

  function startGame() {
    initGame();
    running = true;
    startLoop();
  }

  function togglePause() {
    if (!running || gameOver) return;
    paused = !paused;
    if (paused) {
      stopLoop();
      showOverlay(true, '已暂停', '继续');
    } else {
      showOverlay(false);
      startLoop();
    }
  }

  /* ── 输入处理 ── */
  function setDirection(dir) {
    if (!running || gameOver) return;
    if (paused && dir) {
      paused = false;
      showOverlay(false);
      startLoop();
    }
    if (dir && key(dir) !== OPPOSITE[key(direction)]) {
      nextDirection = dir;
    }
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === ' ' || e.key === 'Escape') {
      e.preventDefault();
      if (gameOver) {
        startGame();
      } else {
        togglePause();
      }
      return;
    }
    const map = {
      ArrowUp: Dir.UP,    w: Dir.UP,    W: Dir.UP,
      ArrowDown: Dir.DOWN,  s: Dir.DOWN,  S: Dir.DOWN,
      ArrowLeft: Dir.LEFT,  a: Dir.LEFT,  A: Dir.LEFT,
      ArrowRight: Dir.RIGHT, d: Dir.RIGHT, D: Dir.RIGHT,
    };
    const d = map[e.key];
    if (d) {
      e.preventDefault();
      setDirection(d);
    }
  });

  document.getElementById('btnUp').addEventListener('click',    () => setDirection(Dir.UP));
  document.getElementById('btnDown').addEventListener('click',  () => setDirection(Dir.DOWN));
  document.getElementById('btnLeft').addEventListener('click',  () => setDirection(Dir.LEFT));
  document.getElementById('btnRight').addEventListener('click', () => setDirection(Dir.RIGHT));
  overlayBtn.addEventListener('click', () => {
    if (gameOver || !running) {
      startGame();
    } else if (paused) {
      togglePause();
    }
  });

  /* ── 启动 ── */
  initGame();
  running = false;
  gameOver = false;
  draw();
  showOverlay(true, '贪吃蛇', '开始游戏');
})();