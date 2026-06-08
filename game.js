// game.js
(function () {
  "use strict";

  // ======================== CONSTANTS ========================
  const COLS = 10;
  const ROWS = 20;
  const CELL = 30;              // pixels per cell
  const PADDING = 20;
  const SIDEBAR = 160;
  const GAP = 30;

  // Standard 7 Tetrominos — 4 rotation states each (clockwise)
  const PIECES = {
    I: {
      shapes: [
        [[0,0,0,0],[1,1,1,1],[0,0,0,0],[0,0,0,0]],
        [[0,0,1,0],[0,0,1,0],[0,0,1,0],[0,0,1,0]],
        [[0,0,0,0],[0,0,0,0],[1,1,1,1],[0,0,0,0]],
        [[0,1,0,0],[0,1,0,0],[0,1,0,0],[0,1,0,0]]
      ],
      color: "#00f0f0"
    },
    O: {
      shapes: [
        [[1,1],[1,1]],
        [[1,1],[1,1]],
        [[1,1],[1,1]],
        [[1,1],[1,1]]
      ],
      color: "#f0f000"
    },
    T: {
      shapes: [
        [[0,1,0],[1,1,1],[0,0,0]],
        [[0,1,0],[0,1,1],[0,1,0]],
        [[0,0,0],[1,1,1],[0,1,0]],
        [[0,1,0],[1,1,0],[0,1,0]]
      ],
      color: "#a000f0"
    },
    S: {
      shapes: [
        [[0,1,1],[1,1,0],[0,0,0]],
        [[0,1,0],[0,1,1],[0,0,1]],
        [[0,0,0],[0,1,1],[1,1,0]],
        [[1,0,0],[1,1,0],[0,1,0]]
      ],
      color: "#00f000"
    },
    Z: {
      shapes: [
        [[1,1,0],[0,1,1],[0,0,0]],
        [[0,0,1],[0,1,1],[0,1,0]],
        [[0,0,0],[1,1,0],[0,1,1]],
        [[0,1,0],[1,1,0],[1,0,0]]
      ],
      color: "#f00000"
    },
    J: {
      shapes: [
        [[1,0,0],[1,1,1],[0,0,0]],
        [[0,1,1],[0,1,0],[0,1,0]],
        [[0,0,0],[1,1,1],[0,0,1]],
        [[0,1,0],[0,1,0],[1,1,0]]
      ],
      color: "#0000f0"
    },
    L: {
      shapes: [
        [[0,0,1],[1,1,1],[0,0,0]],
        [[0,1,0],[0,1,0],[0,1,1]],
        [[0,0,0],[1,1,1],[1,0,0]],
        [[1,1,0],[0,1,0],[0,1,0]]
      ],
      color: "#f0a000"
    }
  };

  const PIECE_TYPES = ["I", "O", "T", "S", "Z", "J", "L"];

  // ELO scoring table indexed by lines cleared
  const SCORE_TABLE = [0, 100, 300, 500, 800];

  function dropInterval(level) {
    return Math.max(100, 800 - level * 70);
  }

  // ======================== GAME STATE ========================
  let board = [];
  let currentPiece = null;
  let nextType = null;
  let score = 0;
  let level = 0;
  let linesCleared = 0;
  let gameOver = false;
  let paused = false;
  let dropTimer = 0;
  let lastTime = 0;

  // Canvas
  let canvas, ctx;

  // ======================== BOARD ========================
  function createBoard() {
    board = [];
    for (let r = 0; r < ROWS; r++) {
      board[r] = new Array(COLS).fill(null);
    }
  }

  function isInBounds(row, col) {
    return row >= 0 && row < ROWS && col >= 0 && col < COLS;
  }

  // ======================== PIECE HELPERS ========================
  function getShape(type, rotation) {
    return PIECES[type].shapes[rotation];
  }

  function getColor(type) {
    return PIECES[type].color;
  }

  function createPiece(type) {
    const shape = getShape(type, 0);
    const w = shape[0].length;
    return {
      type: type,
      rotation: 0,
      x: Math.floor((COLS - w) / 2),
      y: 0
    };
  }

  function getCells(piece) {
    const shape = getShape(piece.type, piece.rotation);
    const cells = [];
    for (let r = 0; r < shape.length; r++) {
      for (let c = 0; c < shape[r].length; c++) {
        if (shape[r][c]) {
          cells.push({ row: piece.y + r, col: piece.x + c });
        }
      }
    }
    return cells;
  }

  // ======================== COLLISION DETECTION ========================
  function isValidPosition(type, rotation, x, y) {
    const shape = getShape(type, rotation);
    for (let r = 0; r < shape.length; r++) {
      for (let c = 0; c < shape[r].length; c++) {
        if (!shape[r][c]) continue;
        const br = y + r;
        const bc = x + c;
        if (br < 0 || br >= ROWS || bc < 0 || bc >= COLS) return false;
        if (board[br][bc] !== null) return false;
      }
    }
    return true;
  }

  function canMove(piece, dx, dy) {
    return isValidPosition(piece.type, piece.rotation, piece.x + dx, piece.y + dy);
  }

  function canRotate(piece, cw) {
    var newRot = cw ? (piece.rotation + 1) % 4 : (piece.rotation + 3) % 4;

    // Basic rotation without offset
    if (isValidPosition(piece.type, newRot, piece.x, piece.y)) {
      return { rotation: newRot, x: piece.x };
    }

    // Wall kick — try horizontal offsets ±1, ±2
    var kicks = cw ? [-1, 1, -2, 2] : [1, -1, 2, -2];
    for (var i = 0; i < kicks.length; i++) {
      var dx = kicks[i];
      if (isValidPosition(piece.type, newRot, piece.x + dx, piece.y)) {
        return { rotation: newRot, x: piece.x + dx };
      }
    }

    return null; // rotation impossible
  }

  // ======================== GHOST PIECE ========================
  function getGhostY() {
    var gy = currentPiece.y;
    while (isValidPosition(currentPiece.type, currentPiece.rotation, currentPiece.x, gy + 1)) {
      gy++;
    }
    return gy;
  }

  // ======================== MOVEMENT & LOCKING ========================
  function movePiece(dx) {
    if (canMove(currentPiece, dx, 0)) {
      currentPiece.x += dx;
    }
  }

  function rotatePiece(cw) {
    var result = canRotate(currentPiece, cw);
    if (result !== null) {
      currentPiece.rotation = result.rotation;
      currentPiece.x = result.x;
    }
  }

  function softDrop() {
    if (canMove(currentPiece, 0, 1)) {
      currentPiece.y += 1;
      return true;
    }
    return false;
  }

  function hardDrop() {
    while (canMove(currentPiece, 0, 1)) {
      currentPiece.y += 1;
    }
    lockPiece();
  }

  function lockPiece() {
    var cells = getCells(currentPiece);
    for (var i = 0; i < cells.length; i++) {
      var row = cells[i].row;
      var col = cells[i].col;
      if (row >= 0 && row < ROWS && col >= 0 && col < COLS) {
        board[row][col] = getColor(currentPiece.type);
      }
    }
    clearLines();
    spawnPiece();
    dropTimer = 0;
  }

  // ======================== LINE CLEARING ========================
  function clearLines() {
    var cleared = 0;
    for (var r = ROWS - 1; r >= 0; r--) {
      if (board[r].every(function (cell) { return cell !== null; })) {
        board.splice(r, 1);
        board.unshift(new Array(COLS).fill(null));
        cleared++;
        r++; // re-check this index
      }
    }

    if (cleared > 0) {
      score += SCORE_TABLE[cleared];
      linesCleared += cleared;
      level = Math.floor(linesCleared / 10);
    }
  }

  // ======================== SPAWN ========================
  function randomPieceType() {
    return PIECE_TYPES[Math.floor(Math.random() * PIECE_TYPES.length)];
  }

  function spawnPiece() {
    var type = nextType || randomPieceType();
    nextType = randomPieceType();
    currentPiece = createPiece(type);

    if (!isValidPosition(currentPiece.type, currentPiece.rotation, currentPiece.x, currentPiece.y)) {
      gameOver = true;
    }
  }

  // ======================== RENDERING ========================
  function drawCell(row, col, color, alpha) {
    alpha = alpha === undefined ? 1 : alpha;
    var x = PADDING + col * CELL;
    var y = PADDING + row * CELL;
    var inset = 1;

    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.fillRect(x + inset, y + inset, CELL - inset * 2, CELL - inset * 2);

    // Top-left highlight
    ctx.fillStyle = "rgba(255,255,255,0.25)";
    ctx.fillRect(x + inset, y + inset, CELL - inset * 2, 3);
    ctx.fillRect(x + inset, y + inset, 3, CELL - inset * 2);

    // Bottom-right shadow
    ctx.fillStyle = "rgba(0,0,0,0.25)";
    ctx.fillRect(x + inset, y + CELL - inset - 3, CELL - inset * 2, 3);
    ctx.fillRect(x + CELL - inset - 3, y + inset, 3, CELL - inset * 2);

    ctx.globalAlpha = 1;
  }

  function drawBoard() {
    var bx = PADDING;
    var by = PADDING;
    var bw = COLS * CELL;
    var bh = ROWS * CELL;

    // Background
    ctx.fillStyle = "#111";
    ctx.fillRect(bx, by, bw, bh);

    // Grid lines
    ctx.strokeStyle = "#1a1a1a";
    ctx.lineWidth = 0.5;
    for (var r = 0; r <= ROWS; r++) {
      ctx.beginPath();
      ctx.moveTo(bx, by + r * CELL);
      ctx.lineTo(bx + bw, by + r * CELL);
      ctx.stroke();
    }
    for (var c = 0; c <= COLS; c++) {
      ctx.beginPath();
      ctx.moveTo(bx + c * CELL, by);
      ctx.lineTo(bx + c * CELL, by + bh);
      ctx.stroke();
    }

    // Border
    ctx.strokeStyle = "#555";
    ctx.lineWidth = 2;
    ctx.strokeRect(bx, by, bw, bh);

    // Locked cells
    for (var r = 0; r < ROWS; r++) {
      for (var c = 0; c < COLS; c++) {
        if (board[r][c] !== null) {
          drawCell(r, c, board[r][c], 1);
        }
      }
    }
  }

  function drawPieceOnBoard(piece, alpha, overrideY) {
    if (!piece || gameOver) return;
    var y = overrideY !== undefined ? overrideY : piece.y;
    var useAlpha = overrideY !== undefined ? 0.25 : (alpha !== undefined ? alpha : 1);
    var color = getColor(piece.type);
    var shape = getShape(piece.type, piece.rotation);
    for (var r = 0; r < shape.length; r++) {
      for (var c = 0; c < shape[r].length; c++) {
        if (shape[r][c]) {
          var row = y + r;
          if (row >= 0) {
            drawCell(row, piece.x + c, color, useAlpha);
          }
        }
      }
    }
  }

  function drawSidebar() {
    var sx = PADDING + COLS * CELL + GAP;
    var sy = PADDING;

    // ── Next piece ──
    ctx.fillStyle = "#ccc";
    ctx.font = "bold 15px monospace";
    ctx.fillText("NEXT", sx, sy + 18);

    var prevX = sx;
    var prevY = sy + 30;
    var prevW = 130;
    var prevH = 100;
    var prevCell = 22;

    ctx.fillStyle = "#111";
    ctx.fillRect(prevX, prevY, prevW, prevH);
    ctx.strokeStyle = "#555";
    ctx.lineWidth = 1;
    ctx.strokeRect(prevX, prevY, prevW, prevH);

    if (nextType) {
      var shape = getShape(nextType, 0);
      var color = getColor(nextType);
      var rows = shape.length;
      var cols = shape[0].length;
      var ox = prevX + (prevW - cols * prevCell) / 2;
      var oy = prevY + (prevH - rows * prevCell) / 2;

      for (var r = 0; r < rows; r++) {
        for (var c = 0; c < cols; c++) {
          if (shape[r][c]) {
            var px = ox + c * prevCell;
            var py = oy + r * prevCell;
            var ins = 1;
            ctx.fillStyle = color;
            ctx.fillRect(px + ins, py + ins, prevCell - ins * 2, prevCell - ins * 2);
            ctx.fillStyle = "rgba(255,255,255,0.2)";
            ctx.fillRect(px + ins, py + ins, prevCell - ins * 2, 2);
            ctx.fillRect(px + ins, py + ins, 2, prevCell - ins * 2);
            ctx.fillStyle = "rgba(0,0,0,0.2)";
            ctx.fillRect(px + ins, py + prevCell - ins - 2, prevCell - ins * 2, 2);
            ctx.fillRect(px + prevCell - ins - 2, py + ins, 2, prevCell - ins * 2);
          }
        }
      }
    }

    // ── Stats ──
    var statsY = prevY + prevH + 28;
    ctx.fillStyle = "#ccc";
    ctx.font = "bold 14px monospace";
    ctx.fillText("SCORE", sx, statsY);
    ctx.font = "20px monospace";
    ctx.fillStyle = "#fff";
    ctx.fillText(String(score), sx, statsY + 22);

    ctx.fillStyle = "#ccc";
    ctx.font = "bold 14px monospace";
    ctx.fillText("LEVEL", sx, statsY + 55);
    ctx.font = "20px monospace";
    ctx.fillStyle = "#fff";
    ctx.fillText(String(level), sx, statsY + 77);

    ctx.fillStyle = "#ccc";
    ctx.font = "bold 14px monospace";
    ctx.fillText("LINES", sx, statsY + 110);
    ctx.font = "20px monospace";
    ctx.fillStyle = "#fff";
    ctx.fillText(String(linesCleared), sx, statsY + 132);

    // ── Controls ──
    var helpY = statsY + 175;
    ctx.font = "12px monospace";
    ctx.fillStyle = "#666";
    var controls = [
      "\u2190 \u2192   Move",
      "\u2191      Rotate",
      "\u2193      Soft Drop",
      "SPC    Hard Drop",
      "P        Pause",
      "R        Restart"
    ];
    for (var i = 0; i < controls.length; i++) {
      ctx.fillText(controls[i], sx, helpY + i * 18);
    }
  }

  function drawOverlay(text, color) {
    ctx.fillStyle = "rgba(0,0,0,0.65)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = color;
    ctx.font = "bold 36px monospace";
    ctx.textAlign = "center";
    ctx.fillText(text, canvas.width / 2, canvas.height / 2 - 10);
    ctx.textAlign = "start";
  }

  function drawGameOverScreen() {
    drawOverlay("GAME OVER", "#f44");

    ctx.fillStyle = "#ddd";
    ctx.font = "16px monospace";
    ctx.textAlign = "center";
    ctx.fillText(
      "Score: " + score + "   Level: " + level + "   Lines: " + linesCleared,
      canvas.width / 2,
      canvas.height / 2 + 30
    );
    ctx.fillText("Press R to restart", canvas.width / 2, canvas.height / 2 + 56);
    ctx.textAlign = "start";
  }

  function render() {
    ctx.fillStyle = "#0d0d1a";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    drawBoard();

    if (currentPiece && !gameOver) {
      var ghostY = getGhostY();
      if (ghostY !== currentPiece.y) {
        drawPieceOnBoard(currentPiece, undefined, ghostY);
      }
      drawPieceOnBoard(currentPiece, 1);
    }

    drawSidebar();

    if (gameOver) {
      drawGameOverScreen();
    } else if (paused) {
      drawOverlay("PAUSED", "#ff0");
    }
  }

  // ======================== GAME LOOP ========================
  function update(dt) {
    if (gameOver || paused) return;

    dropTimer += dt;
    var interval = dropInterval(level);

    while (dropTimer >= interval) {
      dropTimer -= interval;
      if (!softDrop()) {
        lockPiece();
        break; // lockPiece may set gameOver or spawn a new piece
      }
    }
  }

  function gameLoop(timestamp) {
    if (lastTime === 0) lastTime = timestamp;
    var dt = timestamp - lastTime;
    lastTime = timestamp;

    // Clamp dt to avoid spiral-of-death after tab switch
    if (dt > 500) dt = 16;

    update(dt);
    render();
    requestAnimationFrame(gameLoop);
  }

  // ======================== INPUT ========================
  function handleKeyDown(e) {
    // Global keys
    if (e.key === "r" || e.key === "R") {
      restart();
      return;
    }

    if (gameOver) return;

    if (e.key === "p" || e.key === "P") {
      paused = !paused;
      if (!paused) lastTime = performance.now();
      return;
    }

    if (paused) return;

    switch (e.key) {
      case "ArrowLeft":
        e.preventDefault();
        movePiece(-1);
        break;
      case "ArrowRight":
        e.preventDefault();
        movePiece(1);
        break;
      case "ArrowDown":
        e.preventDefault();
        if (!softDrop()) {
          lockPiece();
        }
        dropTimer = 0;
        break;
      case "ArrowUp":
        e.preventDefault();
        rotatePiece(true);
        break;
      case " ":
        e.preventDefault();
        hardDrop();
        break;
    }
  }

  // ======================== TOUCH CONTROLS ========================
  var touchStartX = 0;
  var touchStartY = 0;
  var touchStartTime = 0;

  function handleTouchStart(e) {
    e.preventDefault();
    var t = e.touches[0];
    touchStartX = t.clientX;
    touchStartY = t.clientY;
    touchStartTime = Date.now();
  }

  function handleTouchEnd(e) {
    e.preventDefault();
    if (gameOver || paused) return;

    var t = e.changedTouches[0];
    var dx = t.clientX - touchStartX;
    var dy = t.clientY - touchStartY;
    var dt = Date.now() - touchStartTime;
    var absDx = Math.abs(dx);
    var absDy = Math.abs(dy);

    // Quick tap => rotate
    if (absDx < 12 && absDy < 12 && dt < 250) {
      rotatePiece(true);
      return;
    }

    // Fast downward swipe => hard drop
    if (dy > 60 && dt < 350) {
      hardDrop();
      return;
    }

    // Horizontal / vertical swipe
    if (absDx > absDy) {
      if (dx > 25) movePiece(1);
      else if (dx < -25) movePiece(-1);
    } else {
      if (dy > 25) {
        if (!softDrop()) lockPiece();
        dropTimer = 0;
      }
    }
  }

  // ======================== RESTART ========================
  function restart() {
    createBoard();
    currentPiece = null;
    nextType = null;
    score = 0;
    level = 0;
    linesCleared = 0;
    gameOver = false;
    paused = false;
    dropTimer = 0;
    lastTime = 0;
    nextType = randomPieceType();
    spawnPiece();
  }

  // ======================== INIT ========================
  function init() {
    canvas = document.getElementById("game-canvas");
    ctx = canvas.getContext("2d");

    var canvasWidth = PADDING * 2 + COLS * CELL + GAP + SIDEBAR;
    var canvasHeight = PADDING * 2 + ROWS * CELL;
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;

    createBoard();
    nextType = randomPieceType();
    spawnPiece();

    document.addEventListener("keydown", handleKeyDown);
    canvas.addEventListener("touchstart", handleTouchStart, { passive: false });
    canvas.addEventListener("touchend", handleTouchEnd, { passive: false });

    requestAnimationFrame(gameLoop);
  }

  window.addEventListener("load", init);
})();