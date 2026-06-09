// js/render.js
function draw() {
  const canvas = document.getElementById('game-canvas');
  const ctx = canvas.getContext('2d');

  /* 背景 */
  ctx.fillStyle = '#0a0a0a';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  /* 网格线 */
  ctx.strokeStyle = '#1a1a2e';
  ctx.lineWidth = 0.5;
  for (let y = 0; y <= ROWS; y++) {
    ctx.beginPath();
    ctx.moveTo(0, y * BLOCK_SIZE);
    ctx.lineTo(COLS * BLOCK_SIZE, y * BLOCK_SIZE);
    ctx.stroke();
  }
  for (let x = 0; x <= COLS; x++) {
    ctx.beginPath();
    ctx.moveTo(x * BLOCK_SIZE, 0);
    ctx.lineTo(x * BLOCK_SIZE, ROWS * BLOCK_SIZE);
    ctx.stroke();
  }

  /* 已锁定的方块 */
  for (let y = 0; y < ROWS; y++) {
    for (let x = 0; x < COLS; x++) {
      if (board[y][x]) {
        drawBlock(ctx, x * BLOCK_SIZE, y * BLOCK_SIZE, COLORS[board[y][x]], BLOCK_SIZE);
      }
    }
  }

  /* 当前下落方块 */
  if (currentPiece && !gameOver) {
    const matrix = PIECES[currentPiece.shape][currentPiece.rotation];
    for (let r = 0; r < matrix.length; r++) {
      for (let c = 0; c < matrix[r].length; c++) {
        if (!matrix[r][c]) continue;
        const py = currentPiece.y + r;
        if (py < 0) continue;
        drawBlock(
          ctx,
          (currentPiece.x + c) * BLOCK_SIZE,
          py * BLOCK_SIZE,
          COLORS[currentPiece.shape],
          BLOCK_SIZE
        );
      }
    }
  }

  /* NEXT 预览 */
  drawNextPiece();

  /* 信息面板 */
  updateInfoPanel();
}

function drawBlock(ctx, x, y, color, size) {
  /* 主体 */
  ctx.fillStyle = color;
  ctx.fillRect(x + 1, y + 1, size - 2, size - 2);

  /* 高光（左上） */
  ctx.fillStyle = 'rgba(255,255,255,0.30)';
  ctx.fillRect(x + 1, y + 1, size - 2, 3);
  ctx.fillRect(x + 1, y + 1, 3, size - 2);

  /* 阴影（右下） */
  ctx.fillStyle = 'rgba(0,0,0,0.30)';
  ctx.fillRect(x + 1, y + size - 4, size - 2, 3);
  ctx.fillRect(x + size - 4, y + 1, 3, size - 2);
}

function drawNextPiece() {
  const canvas = document.getElementById('next-canvas');
  if (!canvas || !nextPiece) return;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#0a0a0a';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const matrix = PIECES[nextPiece.shape][0];
  const ps = 18;
  const mw = matrix[0].length;
  const mh = matrix.length;
  const ox = (canvas.width - mw * ps) / 2;
  const oy = (canvas.height - mh * ps) / 2;

  for (let r = 0; r < mh; r++) {
    for (let c = 0; c < mw; c++) {
      if (matrix[r][c]) {
        drawBlock(ctx, ox + c * ps, oy + r * ps, COLORS[nextPiece.shape], ps);
      }
    }
  }
}

function updateInfoPanel() {
  document.getElementById('score-val').textContent = score;
  document.getElementById('level-val').textContent = level;
  document.getElementById('lines-val').textContent = lines;
}

function showGameOver() {
  document.getElementById('final-score').textContent = score;
  document.getElementById('game-over-overlay').style.display = 'flex';
}

function hideGameOver() {
  document.getElementById('game-over-overlay').style.display = 'none';
}