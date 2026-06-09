// js/input.js
const keysDown = {};

function handleKeyDown(e) {
  if (!isRunning || gameOver) return;

  /* 防止长按重复触发 */
  if (keysDown[e.code]) return;
  keysDown[e.code] = true;

  switch (e.code) {
    case 'ArrowLeft':
    case 'KeyA':
      e.preventDefault();
      moveLeft();
      break;
    case 'ArrowRight':
    case 'KeyD':
      e.preventDefault();
      moveRight();
      break;
    case 'ArrowDown':
    case 'KeyS':
      e.preventDefault();
      if (moveDown()) {
        score += 1;
        dropCounter = 0;
      }
      break;
    case 'ArrowUp':
    case 'KeyW':
      e.preventDefault();
      rotatePiece();
      break;
    case 'Space':
      e.preventDefault();
      hardDrop();
      break;
  }
}

function handleKeyUp(e) {
  keysDown[e.code] = false;
}

document.addEventListener('keydown', handleKeyDown);
document.addEventListener('keyup', handleKeyUp);