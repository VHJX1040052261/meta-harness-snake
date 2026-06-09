// js/game.js
/* ========== 碰撞检测 ========== */
function collision(shape, rotation, x, y) {
  const matrix = PIECES[shape][rotation];
  for (let r = 0; r < matrix.length; r++) {
    for (let c = 0; c < matrix[r].length; c++) {
      if (!matrix[r][c]) continue;
      const bx = x + c;
      const by = y + r;
      if (bx < 0 || bx >= COLS || by >= ROWS) return true;
      if (by >= 0 && board[by][bx]) return true;
    }
  }
  return false;
}

/* ========== 移动 ========== */
function moveLeft() {
  if (!currentPiece || gameOver || isPaused) return;
  if (!collision(currentPiece.shape, currentPiece.rotation, currentPiece.x - 1, currentPiece.y)) {
    currentPiece.x--;
  }
}

function moveRight() {
  if (!currentPiece || gameOver || isPaused) return;
  if (!collision(currentPiece.shape, currentPiece.rotation, currentPiece.x + 1, currentPiece.y)) {
    currentPiece.x++;
  }
}

function moveDown() {
  if (!currentPiece) return false;
  if (!collision(currentPiece.shape, currentPiece.rotation, currentPiece.x, currentPiece.y + 1)) {
    currentPiece.y++;
    return true;
  }
  return false;
}

function rotatePiece() {
  if (!currentPiece || gameOver || isPaused) return;
  const newRot = (currentPiece.rotation + 1) % PIECES[currentPiece.shape].length;
  if (!collision(currentPiece.shape, newRot, currentPiece.x, currentPiece.y)) {
    currentPiece.rotation = newRot;
    return;
  }
  const kicks = [1, -1, 2, -2];
  for (const dx of kicks) {
    if (!collision(currentPiece.shape, newRot, currentPiece.x + dx, currentPiece.y)) {
      currentPiece.x += dx;
      currentPiece.rotation = newRot;
      return;
    }
  }
}

function hardDrop() {
  if (!currentPiece || gameOver || isPaused) return;
  let dist = 0;
  while (!collision(currentPiece.shape, currentPiece.rotation, currentPiece.x, currentPiece.y + dist + 1)) {
    dist++;
  }
  currentPiece.y += dist;
  score += dist * 2;
  lockAndAdvance();
}

/* ========== 锁定与消行 ========== */
function lockPiece() {
  const matrix = PIECES[currentPiece.shape][currentPiece.rotation];
  for (let r = 0; r < matrix.length; r++) {
    for (let c = 0; c < matrix[r].length; c++) {
      if (!matrix[r][c]) continue;
      const by = currentPiece.y + r;
      const bx = currentPiece.x + c;
      if (by >= 0 && by < ROWS && bx >= 0 && bx < COLS) {
        board[by][bx] = currentPiece.shape;
      }
    }
  }
}

function clearLines() {
  let cleared = 0;
  for (let y = ROWS - 1; y >= 0; y--) {
    if (board[y].every(cell => cell !== 0)) {
      board.splice(y, 1);
      board.unshift(new Array(COLS).fill(0));
      cleared++;
      y++;
    }
  }
  return cleared;
}

/* ========== 计分系统 ========== */
function updateScore(cleared) {
  if (cleared === 0) return;
  const points = [0, 100, 300, 500, 800];
  score += points[cleared] * level;
  lines += cleared;
  level = Math.floor(lines / 10) + 1;
  dropInterval = Math.max(50, 1000 - (level - 1) * 100);
}

/* ========== 方块生成 ========== */
function createRandomPiece() {
  const shape = PIECE_TYPES[Math.floor(Math.random() * PIECE_TYPES.length)];
  const matrix = PIECES[shape][0];
  const pw = matrix[0].length;
  let sy = 0;
  for (let r = 0; r < matrix.length; r++) {
    if (matrix[r].some(v => v)) { sy = -r; break; }
  }
  return { shape, rotation: 0, x: Math.floor((COLS - pw) / 2), y: sy };
}

function spawnPiece() {
  currentPiece = nextPiece ? nextPiece : createRandomPiece();
  nextPiece = createRandomPiece();
  if (collision(currentPiece.shape, currentPiece.rotation, currentPiece.x, currentPiece.y)) {
    gameOver = true;
    isRunning = false;
  }
}

function lockAndAdvance() {
  lockPiece();
  const cleared = clearLines();
  updateScore(cleared);
  spawnPiece();
  dropCounter = 0;
}

/* ========== 游戏循环 ========== */
let lastTime = 0;
let dropCounter = 0;
let dropInterval = 1000;

function gameLoop(time) {
  if (gameOver) {
    draw();
    showGameOver();
    return;
  }
  if (!isRunning) {
    draw();
    return;
  }
  if (isPaused) {
    lastTime = time;
    draw();
    requestAnimationFrame(gameLoop);
    return;
  }

  const delta = time - lastTime;
  lastTime = time;
  dropCounter += delta;

  if (dropCounter >= dropInterval) {
    if (!moveDown()) {
      lockAndAdvance();
    }
    dropCounter = 0;
  }

  draw();
  requestAnimationFrame(gameLoop);
}