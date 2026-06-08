// game.js
(function () {
  /* ========== Canvas 初始化 ========== */
  const canvas = document.getElementById("gameCanvas");
  const ctx = canvas.getContext("2d");
  const scoreEl = document.getElementById("score");
  const btnStart = document.getElementById("btnStart");
  const btnRestart = document.getElementById("btnRestart");

  /* ========== 常量 ========== */
  const GRID = 20;          // 每格像素
  const COLS = 30;          // 列数
  const ROWS = 20;          // 行数
  const W = COLS * GRID;
  const H = ROWS * GRID;
  canvas.width = W;
  canvas.height = H;

  /* ========== 游戏状态 ========== */
  let snake = [];           // [{x,y}, ...]  头在前
  let food = null;          // {x, y}
  let dir = "";             // 当前方向 "UP"|"DOWN"|"LEFT"|"RIGHT"
  let nextDir = "";         // 缓冲方向（一帧内只接受一次变向）
  let score = 0;
  let gameLoopId = null;
  let running = false;
  let gameOver = false;
  const BASE_INTERVAL = 100; // ms

  /* ========== 绘制 ========== */
  function clear() {
    ctx.fillStyle = "#0f3460";
    ctx.fillRect(0, 0, W, H);
  }

  function drawRect(x, y, color) {
    ctx.fillStyle = color;
    ctx.fillRect(x * GRID + 1, y * GRID + 1, GRID - 2, GRID - 2);
  }

  function drawSnake() {
    snake.forEach(function (seg, i) {
      drawRect(seg.x, seg.y, i === 0 ? "#4ecca3" : "#e94560");
    });
  }

  function drawFood() {
    if (food) drawRect(food.x, food.y, "#f5c518");
  }

  function render() {
    clear();
    drawFood();
    drawSnake();
  }

  /* ========== 食物 ========== */
  function randomFood() {
    const occupied = new Set(snake.map(function (s) { return s.x + "," + s.y; }));
    const free = [];
    for (let x = 0; x < COLS; x++) {
      for (let y = 0; y < ROWS; y++) {
        if (!occupied.has(x + "," + y)) free.push({ x: x, y: y });
      }
    }
    if (free.length === 0) return null; // 胜利
    return free[Math.floor(Math.random() * free.length)];
  }

  function spawnFood() {
    food = randomFood();
    if (!food) {
      endGame(true);
    }
  }

  /* ========== 蛇移动 & 碰撞 ========== */
  function move() {
    dir = nextDir; // 应用缓冲方向
    if (!dir) return;

    const head = snake[0];
    let newHead;
    switch (dir) {
      case "UP":    newHead = { x: head.x, y: head.y - 1 }; break;
      case "DOWN":  newHead = { x: head.x, y: head.y + 1 }; break;
      case "LEFT":  newHead = { x: head.x - 1, y: head.y }; break;
      case "RIGHT": newHead = { x: head.x + 1, y: head.y }; break;
    }

    // 墙壁碰撞
    if (newHead.x < 0 || newHead.x >= COLS || newHead.y < 0 || newHead.y >= ROWS) {
      endGame(false);
      return;
    }

    // 自身碰撞（排除尾巴，因为尾巴即将移走 —— 除非刚吃了食物）
    const willGrow = food && newHead.x === food.x && newHead.y === food.y;
    const checkBody = willGrow ? snake : snake.slice(0, -1);
    for (let i = 0; i < checkBody.length; i++) {
      if (checkBody[i].x === newHead.x && checkBody[i].y === newHead.y) {
        endGame(false);
        return;
      }
    }

    // 插入新头
    snake.unshift(newHead);

    if (willGrow) {
      score += 10;
      scoreEl.textContent = score;
      spawnFood();
      // 不删尾 → 身体增长
    } else {
      snake.pop();
    }
  }

  /* ========== 游戏循环 ========== */
  function tick() {
    if (!running) return;
    move();
    render();
  }

  function startLoop() {
    stopLoop();
    gameLoopId = setInterval(tick, BASE_INTERVAL);
  }

  function stopLoop() {
    if (gameLoopId) {
      clearInterval(gameLoopId);
      gameLoopId = null;
    }
  }

  /* ========== 开始 / 结束 ========== */
  function initState() {
    const startX = Math.floor(COLS / 2);
    const startY = Math.floor(ROWS / 2);
    snake = [
      { x: startX, y: startY },
      { x: startX - 1, y: startY },
      { x: startX - 2, y: startY },
    ];
    dir = "RIGHT";
    nextDir = "RIGHT";
    score = 0;
    scoreEl.textContent = "0";
    gameOver = false;
    spawnFood();
  }

  function startGame() {
    if (running) return;
    if (gameOver) {
      initState();
    }
    running = true;
    btnStart.textContent = "暂停";
    startLoop();
    render();
  }

  function pauseGame() {
    running = false;
    stopLoop();
    btnStart.textContent = "继续";
  }

  function restartGame() {
    stopLoop();
    initState();
    running = false;
    gameOver = false;
    btnStart.textContent = "开始游戏";
    render();
  }

  function endGame(won) {
    running = false;
    stopLoop();
    gameOver = true;
    btnStart.textContent = "开始游戏";
    const msg = won ? "🎉 你赢了！" : "💀 游戏结束！";
    ctx.fillStyle = "rgba(0,0,0,0.7)";
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "#eee";
    ctx.font = "bold 28px 'Courier New'";
    ctx.textAlign = "center";
    ctx.fillText(msg, W / 2, H / 2 - 14);
    ctx.font = "18px 'Courier New'";
    ctx.fillText("最终得分：" + score, W / 2, H / 2 + 22);
    ctx.textAlign = "start";
  }

  /* ========== 键盘 ========== */
  const OPPOSITE = { UP: "DOWN", DOWN: "UP", LEFT: "RIGHT", RIGHT: "LEFT" };
  const KEY_MAP = {
    ArrowUp: "UP", ArrowDown: "DOWN", ArrowLeft: "LEFT", ArrowRight: "RIGHT",
    w: "UP", W: "UP", s: "DOWN", S: "DOWN", a: "LEFT", A: "LEFT", d: "RIGHT", D: "RIGHT",
  };

  document.addEventListener("keydown", function (e) {
    const mapped = KEY_MAP[e.key];
    if (!mapped) return;
    e.preventDefault();
    if (!running && !gameOver) {
      // 未开始 → 首次按键开始
      startGame();
      return;
    }
    // 不允许反向
    if (OPPOSITE[mapped] !== dir) {
      nextDir = mapped;
    }
  });

  /* ========== 按钮事件 ========== */
  btnStart.addEventListener("click", function () {
    if (running) {
      pauseGame();
    } else {
      startGame();
    }
  });

  btnRestart.addEventListener("click", function () {
    restartGame();
  });

  /* ========== 初始渲染 ========== */
  initState();
  render();
})();