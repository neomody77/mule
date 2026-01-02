import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    GeneratedPluginRegistrant.register(with: self)
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}

// 禁用键盘上方的导航工具栏 (Input Accessory View)
extension UITextField {
  open override var inputAccessoryView: UIView? {
    return nil
  }
}

extension UITextView {
  open override var inputAccessoryView: UIView? {
    return nil
  }
}
