"""Modelo simples de uma estufa aquecida por PWM, para testar a malha fechada sem hardware.

Primeira ordem: a cada leitura, T ← T + (T_ambiente + K·PWM − T)·dt/τ, mais o ruído do sensor.
Com os valores padrão, PWM 255 leva a estufa a uns 20 °C acima do ambiente.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Estufa:
    temperatura: float = 25.0       # °C no início
    ambiente: float = 25.0          # °C
    ganho: float = 0.08             # °C de equilíbrio por unidade de PWM
    tau: float = 30.0               # constante de tempo, em leituras
    ruido: float = 0.15             # desvio-padrão do sensor, em °C
    casas: int = 2                  # resolução do valor enviado
    semente: Optional[int] = None
    _aleatorio: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._aleatorio = random.Random(self.semente)

    def ler(self, pwm: float) -> float:
        """Avança uma leitura com o PWM aplicado e devolve o valor medido pelo sensor."""
        alvo = self.ambiente + self.ganho * pwm
        self.temperatura += (alvo - self.temperatura) / self.tau
        return round(self.temperatura + self._aleatorio.gauss(0.0, self.ruido), self.casas)

    def subgrupo(self, pwm: float, n: int = 5) -> List[float]:
        return [self.ler(pwm) for _ in range(n)]
