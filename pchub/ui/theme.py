"""Theme system. Two interchangeable styles (glass, clay) share the same tokens API.

Adding a style = subclass BaseTheme, override paint* and qss values, register in STYLES.
"""
import math

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import QApplication, QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene

from pchub.core.paths import dataDir

ACCENT_PRESETS = [
    ("lavender", "#8B7CF6"), ("sky", "#38BDF8"), ("mint", "#34D399"), ("peach", "#FB923C"),
    ("rose", "#F472B6"), ("coral", "#F87171"), ("gold", "#FBBF24"), ("ice", "#A5B4FC"),
]


def withAlpha(color, alpha):
    newColor = QColor(color)
    newColor.setAlphaF(max(0.0, min(1.0, alpha)))
    return newColor


def mix(colorA, colorB, amount):
    colorA, colorB = QColor(colorA), QColor(colorB)
    return QColor(
        int(colorA.red() + (colorB.red() - colorA.red()) * amount),
        int(colorA.green() + (colorB.green() - colorA.green()) * amount),
        int(colorA.blue() + (colorB.blue() - colorA.blue()) * amount),
        int(colorA.alpha() + (colorB.alpha() - colorA.alpha()) * amount),
    )


def luminance(color):
    color = QColor(color)
    return (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255


def rgba(color, alpha=None):
    color = QColor(color)
    alphaValue = color.alphaF() if alpha is None else alpha
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alphaValue:.3f})"


def blurImage(image, radius):
    """Gaussian-quality blur using QGraphicsBlurEffect (image in device pixels)."""
    if radius <= 0:
        return image
    scene = QGraphicsScene()
    pixmapItem = QGraphicsPixmapItem(QPixmap.fromImage(image))
    blurEffect = QGraphicsBlurEffect()
    blurEffect.setBlurRadius(radius)
    blurEffect.setBlurHints(QGraphicsBlurEffect.QualityHint)
    pixmapItem.setGraphicsEffect(blurEffect)
    scene.addItem(pixmapItem)
    result = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), QRectF(0, 0, image.width(), image.height()))
    painter.end()
    return result


_shadowCache = {}


def shadowImage(width, height, radius, blur, color, devicePixelRatio):
    key = (int(width), int(height), int(radius), int(blur), QColor(color).rgba(), round(devicePixelRatio, 2))
    cached = _shadowCache.get(key)
    if cached is not None:
        return cached
    if len(_shadowCache) > 400:
        _shadowCache.clear()
    padding = blur * 2
    pixelWidth = int((width + padding * 2) * devicePixelRatio)
    pixelHeight = int((height + padding * 2) * devicePixelRatio)
    image = QImage(max(1, pixelWidth), max(1, pixelHeight), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(devicePixelRatio, devicePixelRatio)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(padding, padding, width, height), radius, radius)
    painter.end()
    image = blurImage(image, blur * devicePixelRatio)
    image.setDevicePixelRatio(devicePixelRatio)
    _shadowCache[key] = (image, padding)
    return image, padding


def roundedPath(rect, radius):
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class SurfaceState:
    """Visual state passed to surface painters."""

    def __init__(self, hover=0.0, pressed=False, selected=False, liquid=None, ripple=None, tint=None,
                 disabled=False):
        self.hover = hover
        self.pressed = pressed
        self.selected = selected
        self.liquid = liquid
        self.ripple = ripple
        self.tint = tint
        self.disabled = disabled


class BaseTheme:
    styleId = "base"
    fontFamily = "Segoe UI"
    baseFontSize = 13
    radius = 18
    radiusSmall = 11
    text = QColor("#EEF0FA")
    textMuted = QColor("#A3A8C3")
    textFaint = QColor("#6E7394")
    success = QColor("#34D399")
    warning = QColor("#FBBF24")
    danger = QColor("#F87171")
    windowColor = QColor("#0B0D19")

    def __init__(self, manager):
        self.manager = manager
        self.accent = QColor(manager.accentHex)
        self.accentLight = mix(self.accent, QColor("#FFFFFF"), 0.28)
        self.accentDark = mix(self.accent, QColor("#000000"), 0.35)
        self.accentText = QColor("#11131F") if luminance(self.accent) > 0.62 else QColor("#FFFFFF")

    # background -------------------------------------------------------
    def renderBackground(self, width, height):
        raise NotImplementedError

    def needsBlurredBackground(self):
        return False

    # surfaces ---------------------------------------------------------
    def shadowPad(self, level):
        return 0

    def paintSurface(self, painter, widget, rect, level, state, radius=None):
        raise NotImplementedError

    def paintOverlay(self, painter, rect, level, state, radius=None):
        """Dynamic layer drawn on top of the cached static surface: hover glow, liquid blob, click ripple."""
        radius = self.radius if radius is None else radius
        if state.hover > 0.001:
            painter.fillPath(roundedPath(rect, radius),
                             QColor(255, 255, 255, int(255 * (0.04 if level == 0 else 0.035) * min(1.0, state.hover))))
        self.paintLiquid(painter, rect, state, radius)
        self.paintRipple(painter, rect, state, radius)

    def paintLiquid(self, painter, rect, state, radius):
        liquid = state.liquid
        if not liquid or liquid.intensity <= 0.01:
            return
        strength = self.manager.effectStrength / 100.0
        painter.save()
        painter.setClipPath(roundedPath(rect, radius))
        speed = min(1.0, liquid.speed / 1400.0)
        stretch = 1.0 + speed * 0.9
        blobRadius = max(60.0, min(rect.width(), rect.height()) * 0.55) * (0.85 + 0.15 * liquid.intensity)
        transform = QTransform()
        transform.translate(liquid.x, liquid.y)
        transform.rotateRadians(liquid.angle)
        transform.scale(stretch, 1.0 / math.sqrt(stretch))
        painter.setTransform(transform, True)
        gradient = QRadialGradient(QPointF(0, 0), blobRadius)
        coreColor = self.liquidColor()
        coreAlpha = coreColor.alphaF() * liquid.intensity * (0.35 + 0.9 * strength)
        gradient.setColorAt(0.0, withAlpha(coreColor, coreAlpha))
        gradient.setColorAt(0.45, withAlpha(coreColor, coreAlpha * 0.45))
        gradient.setColorAt(1.0, withAlpha(coreColor, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QPointF(0, 0), blobRadius, blobRadius)
        painter.restore()
        painter.save()
        rimGradient = QRadialGradient(QPointF(liquid.x, liquid.y), blobRadius * 1.3)
        rimColor = self.rimColor()
        rimGradient.setColorAt(0.0, withAlpha(rimColor, rimColor.alphaF() * liquid.intensity * (0.4 + strength)))
        rimGradient.setColorAt(1.0, withAlpha(rimColor, 0))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QBrush(rimGradient), 1.4))
        painter.drawRoundedRect(rect.adjusted(0.7, 0.7, -0.7, -0.7), radius, radius)
        painter.restore()

    def paintRipple(self, painter, rect, state, radius):
        ripple = state.ripple
        if not ripple or ripple.progress >= 1:
            return
        painter.save()
        painter.setClipPath(roundedPath(rect, radius))
        maxRadius = math.hypot(rect.width(), rect.height())
        currentRadius = maxRadius * (0.15 + 0.85 * ripple.progress)
        painter.setPen(Qt.NoPen)
        painter.setBrush(withAlpha(self.liquidColor(), 0.22 * (1 - ripple.progress)))
        painter.drawEllipse(QPointF(ripple.x, ripple.y), currentRadius, currentRadius)
        painter.restore()

    def liquidColor(self):
        return withAlpha(QColor("#FFFFFF"), 0.16)

    def rimColor(self):
        return withAlpha(QColor("#FFFFFF"), 0.55)

    def paintPill(self, painter, rect, state, radius=None):
        """Sidebar item / segmented control highlight."""
        raise NotImplementedError

    def trackColors(self):
        raise NotImplementedError

    # qss ---------------------------------------------------------------
    def qssValues(self):
        raise NotImplementedError

    def qss(self):
        values = self.qssValues()
        values.update({
            "font": self.fontFamily,
            "fontSize": self.baseFontSize,
            "text": self.text.name(),
            "muted": self.textMuted.name(),
            "faint": self.textFaint.name(),
            "accent": self.accent.name(),
            "accentLight": self.accentLight.name(),
            "accentDark": self.accentDark.name(),
            "accentText": self.accentText.name(),
            "accentSoft": rgba(self.accent, 0.22),
            "accentSofter": rgba(self.accent, 0.12),
            "danger": self.danger.name(),
            "dangerSoft": rgba(self.danger, 0.16),
            "dangerBorder": rgba(self.danger, 0.45),
            "success": self.success.name(),
            "warning": self.warning.name(),
            "radius": self.radiusSmall,
            "chevron": self.manager.assetUrl("chevron-down", self.textMuted.name()),
            "check": self.manager.assetUrl("check", self.accentText.name()),
        })
        return QSS_TEMPLATE.format(**values)


class GlassTheme(BaseTheme):
    styleId = "glass"
    fontFamily = "Inter"
    radius = 18
    radiusSmall = 11
    windowColor = QColor("#0A0C18")

    def renderBackground(self, width, height):
        scale = 0.25
        imageWidth, imageHeight = max(8, int(width * scale)), max(8, int(height * scale))
        image = QImage(imageWidth, imageHeight, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        baseGradient = QLinearGradient(0, 0, imageWidth, imageHeight)
        baseGradient.setColorAt(0, QColor("#0A0C18"))
        baseGradient.setColorAt(0.55, QColor("#0E1124"))
        baseGradient.setColorAt(1, QColor("#120F24"))
        painter.fillRect(0, 0, imageWidth, imageHeight, baseGradient)
        accentHue = self.accent
        blobs = [
            (0.10, 0.12, 0.42, accentHue, 0.55),
            (0.86, 0.20, 0.34, QColor("#22D3EE"), 0.32),
            (0.62, 0.92, 0.46, mix(accentHue, QColor("#F472B6"), 0.6), 0.36),
            (0.30, 0.70, 0.26, QColor("#6366F1"), 0.30),
            (0.98, 0.78, 0.22, mix(accentHue, QColor("#FFFFFF"), 0.2), 0.22),
        ]
        diagonal = math.hypot(imageWidth, imageHeight)
        for xFraction, yFraction, radiusFraction, color, alpha in blobs:
            center = QPointF(imageWidth * xFraction, imageHeight * yFraction)
            blobRadius = diagonal * radiusFraction
            gradient = QRadialGradient(center, blobRadius)
            gradient.setColorAt(0, withAlpha(color, alpha))
            gradient.setColorAt(0.55, withAlpha(color, alpha * 0.45))
            gradient.setColorAt(1, withAlpha(color, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(center, blobRadius, blobRadius)
        noiseColor = QColor(255, 255, 255, 6)
        painter.setPen(noiseColor)
        for index in range(0, imageWidth * imageHeight // 40):
            painter.drawPoint((index * 7919) % imageWidth, (index * 104729) % imageHeight)
        painter.end()
        blurred = blurImage(image, 18)
        return image, blurred

    def needsBlurredBackground(self):
        return True

    def shadowPad(self, level):
        return 10 if level == 0 else 0

    def paintSurface(self, painter, widget, rect, level, state, radius=None):
        radius = self.radius if radius is None else radius
        devicePixelRatio = painter.device().devicePixelRatioF()
        opacity = self.manager.glassOpacity
        path = roundedPath(rect, radius)
        if level == 0:
            image, padding = shadowImage(rect.width(), rect.height() * 0.92, radius, 14, QColor(0, 0, 0, 120),
                                         devicePixelRatio)
            painter.drawImage(QPointF(rect.x() - padding, rect.y() - padding + 7), image)
            background = findBackground(widget)
            painter.save()
            painter.setClipPath(path)
            if background is not None and background.blurredImage is not None:
                background.drawBlurredRegion(painter, widget, rect)
            else:
                painter.fillRect(rect, QColor("#12152A"))
            painter.restore()
            fillAlpha = opacity + 0.04 * state.hover
        else:
            fillAlpha = opacity * 0.55 + 0.035 * state.hover
        if state.selected:
            painter.fillPath(path, withAlpha(self.accent, 0.20))
        if state.tint is not None:
            painter.fillPath(path, withAlpha(state.tint, 0.14))
        painter.fillPath(path, QColor(255, 255, 255, int(255 * max(0.0, fillAlpha))))
        highlight = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + min(90.0, rect.height())))
        highlight.setColorAt(0, QColor(255, 255, 255, 22 if level == 0 else 10))
        highlight.setColorAt(1, QColor(255, 255, 255, 0))
        painter.fillPath(path, highlight)
        if state.pressed:
            painter.fillPath(path, QColor(0, 0, 0, 40))
        self.paintLiquid(painter, rect, state, radius)
        self.paintRipple(painter, rect, state, radius)
        border = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if state.selected:
            border.setColorAt(0, withAlpha(self.accentLight, 0.75))
            border.setColorAt(1, withAlpha(self.accent, 0.25))
        else:
            border.setColorAt(0, QColor(255, 255, 255, 62 if level == 0 else 34))
            border.setColorAt(0.5, QColor(255, 255, 255, 18 if level == 0 else 12))
            border.setColorAt(1, QColor(255, 255, 255, 30 if level == 0 else 14))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QBrush(border), 1.0))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    def paintPill(self, painter, rect, state, radius=None):
        radius = self.radiusSmall if radius is None else radius
        path = roundedPath(rect, radius)
        if state.selected:
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            gradient.setColorAt(0, withAlpha(self.accent, 0.34))
            gradient.setColorAt(1, withAlpha(self.accent, 0.12))
            painter.fillPath(path, gradient)
            painter.setPen(QPen(withAlpha(self.accentLight, 0.45), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        elif state.hover > 0:
            painter.fillPath(path, QColor(255, 255, 255, int(20 * state.hover)))

    def trackColors(self):
        return {"off": QColor(255, 255, 255, 34), "offBorder": QColor(255, 255, 255, 40), "knob": QColor("#FFFFFF"),
                "knobOff": QColor("#D8DBEA")}

    def qssValues(self):
        return {
            "inputBg": "rgba(255,255,255,0.06)", "inputBorder": "rgba(255,255,255,0.13)",
            "inputBorderBottom": "rgba(255,255,255,0.13)", "inputHover": "rgba(255,255,255,0.22)",
            "buttonBg": "rgba(255,255,255,0.08)", "buttonHover": "rgba(255,255,255,0.15)",
            "buttonPressed": "rgba(255,255,255,0.05)", "buttonBorder": "rgba(255,255,255,0.15)",
            "buttonBorderTop": "rgba(255,255,255,0.22)", "buttonBorderBottom": "rgba(255,255,255,0.10)",
            "buttonBorderBottomWidth": "1px", "buttonGradTop": "rgba(255,255,255,0.10)",
            "buttonGradBottom": "rgba(255,255,255,0.06)", "popupBg": "#161A2E", "popupBorder": "rgba(255,255,255,0.12)",
            "scrollHandle": "rgba(255,255,255,0.16)", "scrollHandleHover": "rgba(255,255,255,0.28)",
            "grooveBg": "rgba(255,255,255,0.10)", "handleBg": "#FFFFFF", "handleBorder": "rgba(255,255,255,0.6)",
            "divider": "rgba(255,255,255,0.08)", "tooltipBg": "#1B1F36", "selectionBg": rgba(self.accent, 0.35),
            "chipBg": "rgba(255,255,255,0.07)", "chipBorder": "rgba(255,255,255,0.12)",
            "headerBg": "rgba(255,255,255,0.04)",
        }


class ClayTheme(BaseTheme):
    styleId = "clay"
    fontFamily = "Poppins"
    radius = 24
    radiusSmall = 14
    windowColor = QColor("#1E1F2E")
    surfaceTop = QColor("#2E3045")
    surfaceBottom = QColor("#26283A")

    def renderBackground(self, width, height):
        scale = 0.25
        imageWidth, imageHeight = max(8, int(width * scale)), max(8, int(height * scale))
        image = QImage(imageWidth, imageHeight, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(0, 0, imageWidth, imageHeight, QColor("#1E1F2E"))
        diagonal = math.hypot(imageWidth, imageHeight)
        for xFraction, yFraction, radiusFraction, color, alpha in (
                (0.0, 0.0, 0.7, QColor("#2B2D42"), 0.9),
                (0.95, 0.1, 0.45, self.accent, 0.10),
                (0.2, 1.0, 0.5, mix(self.accent, QColor("#38BDF8"), 0.5), 0.07)):
            center = QPointF(imageWidth * xFraction, imageHeight * yFraction)
            blobRadius = diagonal * radiusFraction
            gradient = QRadialGradient(center, blobRadius)
            gradient.setColorAt(0, withAlpha(color, alpha))
            gradient.setColorAt(1, withAlpha(color, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(center, blobRadius, blobRadius)
        painter.end()
        return image, None

    def shadowPad(self, level):
        return 14 if level == 0 else 0

    def liquidColor(self):
        return withAlpha(mix(self.accent, QColor("#FFFFFF"), 0.5), 0.20)

    def rimColor(self):
        return withAlpha(mix(self.accent, QColor("#FFFFFF"), 0.6), 0.6)

    def paintSurface(self, painter, widget, rect, level, state, radius=None):
        radius = self.radius if radius is None else radius
        devicePixelRatio = painter.device().devicePixelRatioF()
        path = roundedPath(rect, radius)
        if level == 0:
            darkImage, darkPadding = shadowImage(rect.width(), rect.height(), radius, 12, QColor(6, 7, 12, 200),
                                                 devicePixelRatio)
            lightImage, lightPadding = shadowImage(rect.width(), rect.height(), radius, 9, QColor(72, 76, 104, 90),
                                                   devicePixelRatio)
            pressShift = 3 if state.pressed else 0
            painter.drawImage(QPointF(rect.x() - lightPadding - 5 + pressShift, rect.y() - lightPadding - 5 + pressShift), lightImage)
            painter.drawImage(QPointF(rect.x() - darkPadding + 7 - pressShift, rect.y() - darkPadding + 9 - pressShift), darkImage)
            fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            topColor = mix(self.surfaceTop, QColor("#FFFFFF"), 0.04 * state.hover)
            bottomColor = mix(self.surfaceBottom, QColor("#FFFFFF"), 0.03 * state.hover)
            if state.selected:
                topColor = mix(topColor, self.accent, 0.35)
                bottomColor = mix(bottomColor, self.accentDark, 0.35)
            if state.tint is not None:
                topColor = mix(topColor, state.tint, 0.12)
                bottomColor = mix(bottomColor, state.tint, 0.08)
            fill.setColorAt(0, topColor)
            fill.setColorAt(1, bottomColor)
            painter.fillPath(path, fill)
            painter.save()
            painter.setClipPath(path)
            innerLight = QLinearGradient(rect.topLeft(), QPointF(rect.left() + 40, rect.top() + 40))
            innerLight.setColorAt(0, QColor(255, 255, 255, 26))
            innerLight.setColorAt(1, QColor(255, 255, 255, 0))
            painter.setPen(QPen(QBrush(innerLight), 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), radius - 1, radius - 1)
            innerDark = QLinearGradient(rect.bottomRight(), QPointF(rect.right() - 60, rect.bottom() - 60))
            innerDark.setColorAt(0, QColor(0, 0, 0, 70))
            innerDark.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setPen(QPen(QBrush(innerDark), 4))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius - 2, radius - 2)
            painter.restore()
        else:
            baseColor = QColor("#1F2131")
            if state.selected:
                baseColor = mix(baseColor, self.accent, 0.25)
            painter.fillPath(path, mix(baseColor, QColor("#FFFFFF"), 0.03 * state.hover))
            painter.save()
            painter.setClipPath(path)
            insetShadow = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + 18))
            insetShadow.setColorAt(0, QColor(0, 0, 0, 90))
            insetShadow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(rect, insetShadow)
            insetLight = QLinearGradient(rect.bottomLeft(), QPointF(rect.left(), rect.bottom() - 10))
            insetLight.setColorAt(0, QColor(255, 255, 255, 16))
            insetLight.setColorAt(1, QColor(255, 255, 255, 0))
            painter.fillRect(rect, insetLight)
            painter.restore()
        if state.pressed and level > 0:
            painter.fillPath(path, QColor(0, 0, 0, 40))
        self.paintLiquid(painter, rect, state, radius)
        self.paintRipple(painter, rect, state, radius)

    def paintPill(self, painter, rect, state, radius=None):
        radius = self.radiusSmall if radius is None else radius
        path = roundedPath(rect, radius)
        if state.selected:
            devicePixelRatio = painter.device().devicePixelRatioF()
            darkImage, padding = shadowImage(rect.width(), rect.height(), radius, 6, QColor(6, 7, 12, 170), devicePixelRatio)
            painter.drawImage(QPointF(rect.x() - padding + 3, rect.y() - padding + 4), darkImage)
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0, self.accentLight)
            gradient.setColorAt(1, self.accent)
            painter.fillPath(path, gradient)
            painter.save()
            painter.setClipPath(path)
            painter.setPen(QPen(QColor(255, 255, 255, 70), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
            painter.restore()
        elif state.hover > 0:
            painter.fillPath(path, QColor(255, 255, 255, int(14 * state.hover)))

    def trackColors(self):
        return {"off": QColor("#191A26"), "offBorder": QColor("#14151F"), "knob": QColor("#F4F5FB"),
                "knobOff": QColor("#C9CCDD")}

    def qssValues(self):
        return {
            "inputBg": "#1B1C2A", "inputBorder": "#15161F", "inputBorderBottom": "#35374C", "inputHover": "#3E4159",
            "buttonBg": "#323449", "buttonHover": "#3A3D55", "buttonPressed": "#2A2C3E", "buttonBorder": "#2A2C3E",
            "buttonBorderTop": "#4B4E68", "buttonBorderBottom": "#15161F", "buttonBorderBottomWidth": "3px",
            "buttonGradTop": "#3A3C53", "buttonGradBottom": "#2C2E41", "popupBg": "#2A2C3F", "popupBorder": "#3A3C52",
            "scrollHandle": "#3A3C52", "scrollHandleHover": "#4A4D66", "grooveBg": "#171823", "handleBg": "#F2F3FA",
            "handleBorder": "#FFFFFF", "divider": "rgba(255,255,255,0.06)", "tooltipBg": "#2E3045",
            "selectionBg": rgba(self.accent, 0.45), "chipBg": "#24263A", "chipBorder": "#1A1B28",
            "headerBg": "#202233",
        }


STYLES = {"glass": GlassTheme, "clay": ClayTheme}


QSS_TEMPLATE = """
* {{ font-family: "{font}", "Segoe UI", sans-serif; font-size: {fontSize}px; color: {text}; outline: none; }}
QWidget {{ background: transparent; }}
QToolTip {{ background: {tooltipBg}; color: {text}; border: 1px solid {popupBorder}; border-radius: 8px; padding: 6px 9px; }}
QLabel {{ background: transparent; }}
QLabel[role="hero"] {{ font-size: 34px; font-weight: 700; }}
QLabel[role="title"] {{ font-size: 22px; font-weight: 700; }}
QLabel[role="subtitle"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="section"] {{ font-size: 12px; font-weight: 600; color: {muted}; letter-spacing: 0.6px; }}
QLabel[role="muted"] {{ color: {muted}; }}
QLabel[role="faint"] {{ color: {faint}; font-size: 12px; }}
QLabel[role="metric"] {{ font-size: 26px; font-weight: 700; }}
QLabel[role="metricSmall"] {{ font-size: 18px; font-weight: 700; }}
QLabel[role="danger"] {{ color: {danger}; }}
QLabel[role="error"] {{ color: {danger}; font-size: 12px; }}
QLabel[role="success"] {{ color: {success}; }}
QLabel[role="warning"] {{ color: {warning}; font-size: 12px; }}
QLabel[role="accent"] {{ color: {accentLight}; font-weight: 600; }}
QLabel[role="chip"] {{ background: {chipBg}; border: 1px solid {chipBorder}; border-radius: 9px; padding: 2px 8px; font-size: 11px; color: {muted}; }}
QLabel[role="chipAccent"] {{ background: {accentSofter}; border: 1px solid {accentSoft}; border-radius: 9px; padding: 2px 8px; font-size: 11px; color: {accentLight}; }}
QLabel[role="chipWarning"] {{ background: rgba(251,191,36,0.12); border: 1px solid rgba(251,191,36,0.35); border-radius: 9px; padding: 2px 8px; font-size: 11px; color: {warning}; }}
QLabel[role="chipDanger"] {{ background: {dangerSoft}; border: 1px solid {dangerBorder}; border-radius: 9px; padding: 2px 8px; font-size: 11px; color: {danger}; }}
QLabel[role="chipSuccess"] {{ background: rgba(52,211,153,0.12); border: 1px solid rgba(52,211,153,0.35); border-radius: 9px; padding: 2px 8px; font-size: 11px; color: {success}; }}
QFrame[role="divider"] {{ background: {divider}; border: none; max-height: 1px; min-height: 1px; }}

QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {buttonGradTop}, stop:1 {buttonGradBottom});
    border: 1px solid {buttonBorder}; border-top-color: {buttonBorderTop};
    border-bottom: {buttonBorderBottomWidth} solid {buttonBorderBottom};
    border-radius: {radius}px; padding: 7px 14px; font-weight: 600; min-height: 18px;
}}
QPushButton:hover {{ background: {buttonHover}; }}
QPushButton:pressed {{ background: {buttonPressed}; border-bottom-width: 1px; padding-top: 8px; }}
QPushButton:disabled {{ color: {faint}; }}
QPushButton:checked {{ background: {accentSoft}; border-color: {accentSoft}; color: {accentLight}; }}
QPushButton[variant="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {accentLight}, stop:1 {accent});
    color: {accentText}; border: 1px solid {accent}; border-top-color: {accentLight};
    border-bottom: {buttonBorderBottomWidth} solid {accentDark};
}}
QPushButton[variant="primary"]:hover {{ background: {accentLight}; }}
QPushButton[variant="primary"]:pressed {{ background: {accent}; border-bottom-width: 1px; }}
QPushButton[variant="primary"]:disabled {{ background: {accentSofter}; color: {faint}; border-color: {accentSofter}; }}
QPushButton[variant="danger"] {{ background: {dangerSoft}; color: {danger}; border: 1px solid {dangerBorder}; border-bottom: {buttonBorderBottomWidth} solid {dangerBorder}; }}
QPushButton[variant="danger"]:hover {{ background: rgba(248,113,113,0.26); }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; padding: 6px 10px; }}
QPushButton[variant="ghost"]:hover {{ background: {buttonBg}; border-color: {buttonBorder}; }}
QPushButton[variant="ghost"]:checked {{ background: {accentSoft}; border-color: {accentSoft}; }}
QPushButton[variant="icon"] {{ background: transparent; border: 1px solid transparent; border-radius: 10px; padding: 6px; min-height: 0px; }}
QPushButton[variant="icon"]:hover {{ background: {buttonBg}; border-color: {buttonBorder}; }}
QPushButton[variant="icon"]:checked {{ background: {accentSoft}; border-color: {accentSoft}; }}
QPushButton[variant="chip"] {{ background: {chipBg}; border: 1px solid {chipBorder}; border-radius: 14px; padding: 5px 12px; font-weight: 500; }}
QPushButton[variant="chip"]:hover {{ border-color: {inputHover}; }}
QPushButton[variant="chip"]:checked {{ background: {accentSoft}; border-color: {accent}; color: {text}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateTimeEdit, QPlainTextEdit, QTextEdit, QComboBox {{
    background: {inputBg}; border: 1px solid {inputBorder}; border-bottom-color: {inputBorderBottom};
    border-radius: {radius}px; padding: 6px 10px; selection-background-color: {selectionBg}; selection-color: {text};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTimeEdit:hover, QComboBox:hover, QPlainTextEdit:hover, QTextEdit:hover {{ border-color: {inputHover}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {accent}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {faint}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0px; border: none; }}
QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {popupBg}; border: 1px solid {popupBorder}; border-radius: 10px; padding: 4px; selection-background-color: {accentSoft}; outline: none; }}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 2px 8px; border-radius: 6px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px; background: {inputBg}; border: 1px solid {inputBorder}; }}
QCheckBox::indicator:hover {{ border-color: {inputHover}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: url("{check}"); }}

QSlider::groove:horizontal {{ height: 6px; background: {grooveBg}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accentDark}, stop:1 {accentLight}); border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {handleBg}; border: 2px solid {handleBorder}; width: 14px; height: 14px; margin: -6px 0; border-radius: 9px; }}
QSlider::handle:horizontal:hover {{ background: {accentLight}; }}
QSlider::handle:horizontal:disabled {{ background: {faint}; }}
QSlider::sub-page:horizontal:disabled {{ background: {faint}; }}

QProgressBar {{ background: {grooveBg}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accentDark}, stop:1 {accentLight}); border-radius: 4px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QAbstractScrollArea {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {scrollHandle}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {scrollHandleHover}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: {scrollHandle}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0px; height: 0px; }}

QMenu {{ background: {popupBg}; border: 1px solid {popupBorder}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 7px; margin: 1px 0px; }}
QMenu::item:selected {{ background: {accentSoft}; }}
QMenu::item:disabled {{ color: {faint}; }}
QMenu::separator {{ height: 1px; background: {divider}; margin: 5px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; margin-left: 6px; }}
QMenu::indicator:checked {{ image: url("{check}"); background: {accent}; border-radius: 4px; }}
QMenu::indicator:unchecked {{ background: {inputBg}; border: 1px solid {inputBorder}; border-radius: 4px; }}

QTableWidget, QTableView, QListWidget, QTreeWidget {{ background: transparent; border: none; gridline-color: {divider}; selection-background-color: {accentSoft}; alternate-background-color: transparent; }}
QTableWidget::item, QTableView::item {{ padding: 4px 6px; border-bottom: 1px solid {divider}; }}
QListWidget::item {{ border-radius: 8px; padding: 6px; }}
QListWidget::item:selected {{ background: {accentSoft}; color: {text}; }}
QHeaderView::section {{ background: {headerBg}; color: {muted}; border: none; border-bottom: 1px solid {divider}; padding: 6px 8px; font-weight: 600; font-size: 12px; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; border-radius: 9px; color: {muted}; font-weight: 600; }}
QTabBar::tab:selected {{ background: {accentSoft}; color: {text}; }}
QTabWidget::pane {{ border: none; }}
QDialog {{ background: transparent; }}
"""


class ThemeManager(QObject):
    changed = Signal()
    effectsChanged = Signal()

    def __init__(self, appStore, parent=None):
        super().__init__(parent)
        self.appStore = appStore
        self._theme = None
        self.rebuild()
        appStore.changed.connect(self._onStoreChanged)

    @property
    def styleId(self):
        styleValue = self.appStore.get("appearance.style", "glass")
        return styleValue if styleValue in STYLES else "glass"

    @property
    def accentHex(self):
        return self.appStore.get("appearance.accent", ACCENT_PRESETS[0][1])

    @property
    def glassOpacity(self):
        return self.appStore.get("appearance.glassOpacity", 7) / 100.0

    @property
    def animations(self):
        return bool(self.appStore.get("appearance.animations", True))

    @property
    def mouseEffects(self):
        return bool(self.appStore.get("appearance.mouseEffects", True))

    @property
    def effectStrength(self):
        return self.appStore.get("appearance.effectStrength", 60)

    @property
    def parallax(self):
        return bool(self.appStore.get("appearance.parallax", False))

    def current(self):
        return self._theme

    def rebuild(self):
        self._theme = STYLES[self.styleId](self)

    def assetUrl(self, iconName, colorHex):
        from pchub.ui.icons import _svgSource
        folder = dataDir() / "cache" / "qss"
        folder.mkdir(parents=True, exist_ok=True)
        filePath = folder / f"{iconName}-{colorHex.lstrip('#')}.svg"
        if not filePath.exists():
            filePath.write_text(_svgSource(iconName).replace("currentColor", colorHex).replace('stroke-width="2"', 'stroke-width="3"'),
                                encoding="utf-8")
        return filePath.as_posix()

    def apply(self, application=None):
        application = application or QApplication.instance()
        if application is None:
            return
        font = QFont(self._theme.fontFamily)
        font.setPixelSize(self._theme.baseFontSize)
        font.setHintingPreference(QFont.PreferNoHinting)
        application.setFont(font)
        application.setStyleSheet(self._theme.qss())
        for widget in application.allWidgets():
            widget.update()

    def _onStoreChanged(self, key, value):
        if key.startswith("appearance.") or key == "":
            if key in ("appearance.style", "appearance.accent", "appearance.glassOpacity", ""):
                self.rebuild()
                self.apply()
                self.changed.emit()
            else:
                self.effectsChanged.emit()
                for widget in (QApplication.instance().allWidgets() if QApplication.instance() else []):
                    widget.update()


_managerInstance = None


def setThemeManager(manager):
    global _managerInstance
    _managerInstance = manager


def themeManager():
    return _managerInstance


def theme():
    return _managerInstance.current()


def findBackground(widget):
    from pchub.ui.background import BackgroundWidget
    cachedBackground = getattr(widget, "_cachedBackground", None)
    if cachedBackground is not None:
        try:
            if cachedBackground.isAncestorOf(widget):
                return cachedBackground
        except RuntimeError:
            pass
    parentWidget = widget.parentWidget() if widget is not None else None
    while parentWidget is not None:
        if isinstance(parentWidget, BackgroundWidget):
            try:
                widget._cachedBackground = parentWidget
            except AttributeError:
                pass
            return parentWidget
        parentWidget = parentWidget.parentWidget()
    return None
