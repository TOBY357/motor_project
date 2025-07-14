#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# created by TOBY

"""
キー操作:
  W/A/S/D/Q/E : 前進/左旋回/後退/右旋回/左折/右折
  K/L         : パワー +/-（5%単位）
  ,/.         : 左右バランス調整（±0.05単位）
  スペース    : 停止
  X           : プログラム終了
"""

import pigpio
import sys
import termios
import tty
import time


class MotorController:
    """
    モーターを制御するクラス。
    GPIOの初期設定から速度制御、動作コマンド、パワー・バランス調整までを提供。
    """

    def __init__(
        self,
        pi: pigpio.pi,
        pins: dict[str, int],
        freq: int = 50,
        pwm_range: int = 100
    ) -> None:
        """
        Args:
            pi: pigpioインスタンス
            pins: {'L_A1':4, 'L_A2':17, 'R_B1':27, 'R_B2':22}
            freq: PWM周波数(Hz)
            pwm_range: PWM分解能(0~pwm_range)
        """
        self.pi = pi
        self.pins = pins
        self.freq = freq
        self.pwm_range = pwm_range

        # 初期設定: 全ピンを出力モードにし、PWM設定を行う
        for pin_name, pin_num in self.pins.items():
            self.pi.set_mode(pin_num, pigpio.OUTPUT)
            self.pi.set_PWM_frequency(pin_num, self.freq)
            self.pi.set_PWM_range(pin_num, self.pwm_range)

        # 初期パラメータ
        self.power = 80           # 基本出力強度(0~100)
        self.balance = [1.0, 1.0] # 左右バランス[L, R]

    def _apply_pwm(
        self,
        forward_pin: int,
        backward_pin: int,
        speed: float
    ) -> None:
        """
        単一モーターにPWM信号を適用。

        speed > 0: forward_pinをPWM出力
        speed < 0: backward_pinをPWM出力
        """
        duty_forward = max(0.0, speed)
        duty_backward = max(0.0, -speed)

        self.pi.set_PWM_dutycycle(forward_pin, duty_forward)
        self.pi.set_PWM_dutycycle(backward_pin, duty_backward)

    def set_speed(
        self,
        left_speed: float,
        right_speed: float
    ) -> None:
        """
        左右モーターを同時に制御。

        Args:
            left_speed: -100~100
            right_speed: -100~100
        """
        # バランス補正を適用
        left_actual = left_speed * self.balance[0]
        right_actual = right_speed * self.balance[1]

        # 前進/後退に応じてPWMを送信
        self._apply_pwm(
            self.pins['L_f'],
            self.pins['L_b'],
            left_actual
        )
        self._apply_pwm(
            self.pins['R_f'],
            self.pins['R_b'],
            right_actual
        )

    def stop(self) -> None:
        """モーター停止 (速度0)。"""
        self.set_speed(0.0, 0.0)

    # --- 走行コマンド ---
    def forward(self) -> None:
        """前進: 両輪正転。"""
        self.set_speed(self.power, self.power)

    def backward(self) -> None:
        """後退: 両輪逆転。"""
        self.set_speed(-self.power, -self.power)

    def turn_left(self) -> None:
        """その場左旋回: 左逆, 右正。"""
        self.set_speed(-self.power, self.power)

    def turn_right(self) -> None:
        """その場右旋回: 左正, 右逆。"""
        self.set_speed(self.power, -self.power)

    def pivot_left(self) -> None:
        """左小旋回: 左正, 右停止。"""
        self.set_speed(self.power, 0.0)

    def pivot_right(self) -> None:
        """右小旋回: 左停止, 右正。"""
        self.set_speed(0.0, self.power)

    # --- 調整コマンド ---
    def adjust_power(self, delta: int) -> None:
        """
        パワーを+/-deltaだけ増減し、0~100にクランプ。
        """
        self.power = max(0, min(100, self.power + delta))
        print(f"Power: {self.power}%")

    def adjust_balance(self, delta: float) -> None:
        """
        左右バランスを調整し、[0.5, 1.5]にクランプ。
        """
        new_left = self.balance[0] + delta
        new_right = self.balance[1] - delta
        # 範囲制限
        self.balance[0] = max(0.5, min(1.5, new_left))
        self.balance[1] = max(0.5, min(1.5, new_right))
        print(f"Balance: L={self.balance[0]:.2f}, R={self.balance[1]:.2f}")


class KeyReader:
    """
    ノンブロッキングで1文字取得するユーティリティ。
    使用時はコンテキストマネージャで囲む。
    """

    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.orig = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(
        self,
        exc_type,
        exc_val,
        exc_tb
    ) -> None:
        termios.tcsetattr(
            self.fd,
            termios.TCSADRAIN,
            self.orig
        )

    def get(self) -> str:
        """1文字読み取り (小文字に正規化)。"""
        ch = sys.stdin.read(1)
        return ch.lower()


def main() -> None:
    """
    メインループ: キー入力を受け付けて各操作を実行。
    """
    # pigpio初期化
    pi = pigpio.pi()
    pins = {'L_A1': 12, 'L_A2': 13, 'R_B1': 18, 'R_B2': 19}
    controller = MotorController(pi, pins)

    # キーとメソッドの対応表
    actions: dict[str, callable] = {
        'w': controller.forward,
        's': controller.backward,
        'a': controller.turn_left,
        'd': controller.turn_right,
        'q': controller.pivot_left,
        'e': controller.pivot_right,
        'k': lambda: controller.adjust_power(+5),
        'l': lambda: controller.adjust_power(-5),
        ',': lambda: controller.adjust_balance(+0.05),
        '.': lambda: controller.adjust_balance(-0.05),
        ' ': controller.stop,
    }

    print("--- Control Started: Press X to exit ---")

    # キー取得用の設定
    with KeyReader() as reader:
        while True:
            key = reader.get()
            if not key:
                time.sleep(0.05)
                continue
            if key == 'x':
                break

            action = actions.get(key)
            if action:
                action()

    # 終了処理
    controller.stop()
    pi.stop()
    print("Exited.")


if __name__ == '__main__':
    main()
