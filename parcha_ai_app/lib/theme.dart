
import 'package:flutter/material.dart';
import 'models.dart'; // Import ConfidenceLevel enum

/// Professional healthcare color palette
class AppColors {
  // Primary colors - calming medical blues/teals
  static const Color primary = Color(0xFF0D7C8C); // Deep teal
  static const Color primaryLight = Color(0xFF4FA8B5);
  static const Color primaryDark = Color(0xFF005662);
  
  // Secondary colors - warm accent
  static const Color secondary = Color(0xFF00897B); // Teal accent
  static const Color secondaryLight = Color(0xFF4DB6AC);
  
  // Background colors
  static const Color background = Color(0xFFF8FAFB);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceVariant = Color(0xFFF1F5F7);
  
  // Confidence level colors
  static const Color confidenceHigh = Color(0xFF2E7D32); // Green - safe
  static const Color confidenceMedium = Color(0xFFF57C00); // Orange - caution
  static const Color confidenceLow = Color(0xFFD32F2F); // Red - warning
  static const Color confidenceCritical = Color(0xFF880E4F); // Deep red - critical
  
  // Semantic colors
  static const Color success = Color(0xFF388E3C);
  static const Color warning = Color(0xFFF57C00);
  static const Color error = Color(0xFFD32F2F);
  static const Color info = Color(0xFF1976D2);
  
  // Text colors
  static const Color textPrimary = Color(0xFF1A1A1A);
  static const Color textSecondary = Color(0xFF666666);
  static const Color textTertiary = Color(0xFF999999);
  static const Color textOnPrimary = Color(0xFFFFFFFF);
  
  // Border colors
  static const Color borderLight = Color(0xFFE0E0E0);
  static const Color borderMedium = Color(0xFFBDBDBD);
  
  // Special
  static const Color urduBackground = Color(0xFFFFF8E1); // Light amber for Urdu text
  static const Color disclaimerBackground = Color(0xFFFFF3E0); // Light orange
}

/// Typography scale for healthcare app
class AppTextStyles {
  // Headers
  static const TextStyle h1 = TextStyle(
    fontSize: 28,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.5,
    height: 1.2,
    color: AppColors.textPrimary,
  );
  
  static const TextStyle h2 = TextStyle(
    fontSize: 24,
    fontWeight: FontWeight.w600,
    letterSpacing: -0.3,
    height: 1.3,
    color: AppColors.textPrimary,
  );
  
  static const TextStyle h3 = TextStyle(
    fontSize: 20,
    fontWeight: FontWeight.w600,
    height: 1.4,
    color: AppColors.textPrimary,
  );
  
  // Body text
  static const TextStyle bodyLarge = TextStyle(
    fontSize: 17,
    fontWeight: FontWeight.w400,
    height: 1.5,
    color: AppColors.textPrimary,
  );
  
  static const TextStyle bodyMedium = TextStyle(
    fontSize: 15,
    fontWeight: FontWeight.w400,
    height: 1.5,
    color: AppColors.textPrimary,
  );
  
  static const TextStyle bodySmall = TextStyle(
    fontSize: 13,
    fontWeight: FontWeight.w400,
    height: 1.4,
    color: AppColors.textSecondary,
  );
  
  // Special text styles
  static const TextStyle medicineName = TextStyle(
    fontSize: 20,
    fontWeight: FontWeight.w700,
    height: 1.3,
    color: AppColors.textPrimary,
  );
  
  static const TextStyle fieldLabel = TextStyle(
    fontSize: 13,
    fontWeight: FontWeight.w600,
    letterSpacing: 0.5,
    color: AppColors.textSecondary,
  );
  
  static const TextStyle fieldValue = TextStyle(
    fontSize: 16,
    fontWeight: FontWeight.w400,
    height: 1.4,
    color: AppColors.textPrimary,
  );
  
  static const TextStyle urduText = TextStyle(
    fontSize: 18,
    fontWeight: FontWeight.w400,
    height: 1.8,
    letterSpacing: 0.3,
    color: AppColors.textPrimary,
  );
  
  static const TextStyle disclaimer = TextStyle(
    fontSize: 14,
    fontWeight: FontWeight.w500,
    height: 1.5,
    color: Color(0xFFE65100), // Deep orange
  );
  
  static const TextStyle badge = TextStyle(
    fontSize: 11,
    fontWeight: FontWeight.w700,
    letterSpacing: 0.5,
    color: AppColors.textOnPrimary,
  );
}

/// Spacing constants
class AppSpacing {
  static const double xs = 4.0;
  static const double sm = 8.0;
  static const double md = 16.0;
  static const double lg = 24.0;
  static const double xl = 32.0;
  static const double xxl = 48.0;
}

/// Border radius constants
class AppRadius {
  static const double sm = 8.0;
  static const double md = 12.0;
  static const double lg = 16.0;
  static const double xl = 20.0;
  static const double pill = 100.0;
}

/// Get Material theme for the app
ThemeData getAppTheme() {
  return ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      primary: AppColors.primary,
      secondary: AppColors.secondary,
      background: AppColors.background,
      surface: AppColors.surface,
      error: AppColors.error,
      brightness: Brightness.light,
    ),
    scaffoldBackgroundColor: AppColors.background,
    
    // Typography
    textTheme: const TextTheme(
      displayLarge: AppTextStyles.h1,
      displayMedium: AppTextStyles.h2,
      displaySmall: AppTextStyles.h3,
      bodyLarge: AppTextStyles.bodyLarge,
      bodyMedium: AppTextStyles.bodyMedium,
      bodySmall: AppTextStyles.bodySmall,
    ),
    
    // AppBar
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.primary,
      foregroundColor: AppColors.textOnPrimary,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontSize: 20,
        fontWeight: FontWeight.w600,
        color: AppColors.textOnPrimary,
      ),
    ),
    
    // Card
    cardTheme: CardThemeData(
      color: AppColors.surface,
      elevation: 2,
      shadowColor: Colors.black.withOpacity(0.05),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      margin: EdgeInsets.zero,
    ),
    
    // Elevated Button
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.primary,
        foregroundColor: AppColors.textOnPrimary,
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.md,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
        elevation: 2,
        textStyle: const TextStyle(
          fontSize: 16,
          fontWeight: FontWeight.w600,
        ),
      ),
    ),
    
    // Outlined Button
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.primary,
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
        ),
        side: const BorderSide(
          color: AppColors.borderMedium,
          width: 1.5,
        ),
      ),
    ),
    
    // Divider
    dividerTheme: const DividerThemeData(
      color: AppColors.borderLight,
      thickness: 1,
      space: AppSpacing.lg,
    ),
  );
}

/// Confidence badge color based on level
Color getConfidenceColor(ConfidenceLevel level) {
  switch (level) {
    case ConfidenceLevel.high:
      return AppColors.confidenceHigh;
    case ConfidenceLevel.medium:
      return AppColors.confidenceMedium;
    case ConfidenceLevel.low:
      return AppColors.confidenceLow;
    case ConfidenceLevel.critical:
      return AppColors.confidenceCritical;
  }
}

/// Confidence badge icon based on level
IconData getConfidenceIcon(ConfidenceLevel level) {
  switch (level) {
    case ConfidenceLevel.high:
      return Icons.verified;
    case ConfidenceLevel.medium:
      return Icons.info_outline;
    case ConfidenceLevel.low:
      return Icons.warning_amber_rounded;
    case ConfidenceLevel.critical:
      return Icons.error_outline;
  }
}

// Note: ConfidenceLevel enum is defined in models.dart
