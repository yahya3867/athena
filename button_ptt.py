import threading
from enum import Enum


class State(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    STREAMING = "streaming"
    ERROR = "error"


STATE_COLORS = {
    State.IDLE:          (90, 90, 90),     # visible when idle (was 40 = too dim / looked black)
    State.LISTENING:     (0, 80, 255),     # blue
    State.TRANSCRIBING:  (255, 200, 0),    # yellow
    State.THINKING:      (255, 200, 0),    # yellow
    State.STREAMING:     (0, 200, 50),     # green
    State.ERROR:         (255, 0, 0),      # red
}


class ButtonPTT:
    """Tracks push-to-talk button and application state."""

    def __init__(self, board, on_press_cb=None, on_release_cb=None, on_cancel_cb=None, cancel_allowed_cb=None, on_any_press_cb=None, on_abort_listening_cb=None):
        self._board = board
        self._on_press = on_press_cb
        self._on_release = on_release_cb
        self._on_cancel = on_cancel_cb
        self._on_any_press = on_any_press_cb  # called on every press first (e.g. wake display)
        self._on_abort_listening = on_abort_listening_cb  # called when press while LISTENING (stuck / abort)
        self._cancel_allowed = cancel_allowed_cb
        self._state = State.IDLE
        self._lock = threading.Lock()

        board.on_button_press(self._handle_press)
        board.on_button_release(self._handle_release)

    @property
    def state(self) -> State:
        return self._state

    @state.setter
    def state(self, new_state: State):
        with self._lock:
            self._state = new_state
            self._update_led(new_state)

    def _update_led(self, state: State):
        # Skip backlight for IDLE so main can use display.set_backlight() and screen stays visible
        if state == State.IDLE:
            return
        color = STATE_COLORS.get(state, (40, 40, 40))
        try:
            self._board.set_backlight_color(*color)
        except AttributeError:
            pass

    def _handle_press(self):
        # Always wake display on any press (so button works even when screen looked black)
        if self._on_any_press:
            self._on_any_press()
        # Stuck in LISTENING (release never fired)? Abort so next press can start fresh.
        if self._state == State.LISTENING:
            if self._on_abort_listening:
                self._on_abort_listening()
            self._state = State.IDLE
            self._update_led(State.IDLE)
            return
        # Active operation (transcribing/thinking/streaming): cancel and return to idle.
        if self._state in (State.TRANSCRIBING, State.THINKING, State.STREAMING):
            if self._cancel_allowed and not self._cancel_allowed():
                return
            self._state = State.IDLE
            self._update_led(State.IDLE)
            if self._on_cancel:
                self._on_cancel()
            return
        if self._state not in (State.IDLE, State.ERROR):
            return
        self._state = State.LISTENING
        self._update_led(State.LISTENING)
        if self._on_press:
            self._on_press()

    def _handle_release(self):
        if self._state != State.LISTENING:
            return
        if self._on_release:
            self._on_release()
